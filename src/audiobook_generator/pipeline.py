"""Auditable, resumable audiobook build pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .audio import merge_wav_files
from .cache import atomic_write_json, content_key, sha256_text
from .config import OpenAIConfig, load_voice_config
from .errors import BuildError, InputError
from .llm import OpenAILLMClient
from .models import (
    BookManifest,
    BookManifestChapter,
    BookSpec,
    Chapter,
    ChapterManifest,
    VoiceConfig,
)
from .sources import BookSelectionError, load_book_directory
from .speaker import SpeakerAllocator, SpeakerMode, VoiceRegistry
from .text import chunk_text, safe_filename_component, split_narration_and_dialogue
from .tts import OpenAITTSClient, SynthesisResult

DEFAULT_MAX_CHAPTERS = 100
DEFAULT_MAX_TTS_CHARACTERS = 1_000_000
ABSOLUTE_MAX_CHAPTERS = 10_000


@dataclass(frozen=True, slots=True)
class BuildOptions:
    chapter_indexes: frozenset[int] | None = None
    speaker_mode: SpeakerMode = "auto"
    dry_run: bool = False
    force: bool = False
    max_chapters: int = DEFAULT_MAX_CHAPTERS
    max_tts_characters: int = DEFAULT_MAX_TTS_CHARACTERS

    def __post_init__(self) -> None:
        if self.speaker_mode not in {"auto", "llm", "rules"}:
            raise InputError("speaker mode must be auto, llm, or rules")
        if self.max_chapters <= 0:
            raise InputError("max chapters must be greater than zero")
        if self.max_chapters > ABSOLUTE_MAX_CHAPTERS:
            raise InputError(f"max chapters must not exceed {ABSOLUTE_MAX_CHAPTERS}")
        if self.max_tts_characters <= 0:
            raise InputError("max TTS characters must be greater than zero")


@dataclass(frozen=True, slots=True)
class BuildPlan:
    fingerprint: str
    chapter_count: int
    character_count: int
    estimated_llm_requests: int
    llm_cache_hits: int
    estimated_tts_requests: int
    tts_cache_hits: int

    @property
    def paid_llm_requests(self) -> int:
        return max(0, self.estimated_llm_requests - self.llm_cache_hits)

    @property
    def paid_tts_requests(self) -> int:
        return max(0, self.estimated_tts_requests - self.tts_cache_hits)


@dataclass(frozen=True, slots=True)
class ChapterBuildReport:
    index: int
    audio_path: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class BuildReport:
    plan: BuildPlan
    book_manifest_path: Path | None
    chapters: list[ChapterBuildReport] = field(default_factory=list)


class AudiobookBuilder:
    """Create WAV chapters using validated local book and voice schemas."""

    def __init__(
        self,
        config: OpenAIConfig,
        voice_config_path: str | Path | None = None,
        *,
        voice_config: VoiceConfig | None = None,
        tts_client: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        if voice_config is not None and voice_config_path is not None:
            raise InputError("provide either a voices path or a VoiceConfig, not both")
        self.config = config
        self.voice_config = voice_config or _load_voices(voice_config_path)
        self.voice_registry = VoiceRegistry.from_config(self.voice_config)
        self._tts_client_override = tts_client
        self._llm_client_override = llm_client

    def plan_from_book_dir(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        options: BuildOptions | None = None,
    ) -> BuildPlan:
        options = options or BuildOptions()
        chapters = self._load_selected_chapters(input_dir, options)[1]
        tts, llm = self._clients(output_dir, options.speaker_mode)
        return self._make_plan(chapters, options, tts, llm)

    def build_from_book_dir(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        options: BuildOptions | None = None,
        *,
        approved_plan: BuildPlan | None = None,
    ) -> BuildReport:
        options = options or BuildOptions()
        book, chapters = self._load_selected_chapters(input_dir, options)
        tts, llm = self._clients(output_dir, options.speaker_mode)
        plan = self._make_plan(chapters, options, tts, llm)
        if options.dry_run:
            return BuildReport(plan=plan, book_manifest_path=None)
        if approved_plan is not None:
            if approved_plan.fingerprint != plan.fingerprint:
                raise InputError(
                    "Build inputs changed after the displayed estimate; review it again."
                )
            if (
                plan.paid_llm_requests > approved_plan.paid_llm_requests
                or plan.paid_tts_requests > approved_plan.paid_tts_requests
            ):
                raise InputError(
                    "Cache state changed after the displayed estimate; review it again."
                )
        if not self.config.api_key and self._tts_client_override is None:
            raise InputError("OPENAI_API_KEY is required unless --dry-run is used.")

        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        allocator = SpeakerAllocator(
            self.voice_registry,
            llm_client=llm,
            mode=options.speaker_mode,
        )
        chapter_reports: list[ChapterBuildReport] = []
        book_entries: list[BookManifestChapter] = []
        for chapter in chapters:
            report, manifest = self._build_chapter(
                chapter,
                destination,
                allocator,
                tts,
                force=options.force,
            )
            chapter_reports.append(report)
            book_entries.append(
                BookManifestChapter(
                    index=chapter.index,
                    title=chapter.title,
                    audio_file=report.audio_path.relative_to(destination).as_posix(),
                    manifest_file=report.manifest_path.relative_to(destination).as_posix(),
                    character_count=manifest.character_count,
                    sha256=manifest.sha256,
                )
            )

        book_manifest = BookManifest(
            schema_version=1,
            title=book.book.title,
            author=book.book.author,
            chapters=book_entries,
            ai_generated=True,
        )
        book_manifest_path = destination / "book-manifest.json"
        atomic_write_json(book_manifest_path, book_manifest.model_dump(mode="json"))
        return BuildReport(
            plan=plan,
            book_manifest_path=book_manifest_path,
            chapters=chapter_reports,
        )

    def _clients(
        self,
        output_dir: str | Path,
        mode: SpeakerMode,
    ) -> tuple[Any, Any | None]:
        cache_root = Path(output_dir).resolve() / ".cache"
        tts = self._tts_client_override or OpenAITTSClient(
            self.config,
            cache_dir=cache_root / "tts",
        )
        if mode == "rules":
            llm = None
        else:
            llm = self._llm_client_override or OpenAILLMClient(
                self.config,
                cache_dir=cache_root / "llm",
            )
        return tts, llm

    def _make_plan(
        self,
        chapters: list[Chapter],
        options: BuildOptions,
        tts: Any,
        llm: Any | None,
    ) -> BuildPlan:
        llm_requests = 0
        llm_hits = 0
        tts_requests = 0
        tts_hits = 0
        planning_allocator = SpeakerAllocator(self.voice_registry, mode="rules")

        for chapter in chapters:
            items = split_narration_and_dialogue(chapter.text)
            if options.speaker_mode != "rules":
                for index, (kind, quote) in enumerate(items):
                    if kind != "dialogue":
                        continue
                    llm_requests += 1
                    previous = _adjacent_narration(items, index, -1)
                    following = _adjacent_narration(items, index, 1)
                    if llm is not None and _safe_cache_probe(
                        llm,
                        previous,
                        quote,
                        following,
                    ):
                        llm_hits += 1

            lines, _ = planning_allocator.allocate(chapter.text)
            for line in lines:
                for part in chunk_text(line.text, self.config.max_input_chars):
                    tts_requests += 1
                    cache_hit_is_safe = options.speaker_mode == "rules" or line.kind == "narration"
                    if (
                        cache_hit_is_safe
                        and not options.force
                        and _safe_tts_cache_probe(
                            tts,
                            part,
                            line.voice,
                            line.instructions,
                        )
                    ):
                        tts_hits += 1

        return BuildPlan(
            fingerprint=self._plan_fingerprint(chapters, options),
            chapter_count=len(chapters),
            character_count=sum(len(chapter.text) for chapter in chapters),
            estimated_llm_requests=llm_requests,
            llm_cache_hits=llm_hits,
            estimated_tts_requests=tts_requests,
            tts_cache_hits=tts_hits,
        )

    def _plan_fingerprint(self, chapters: list[Chapter], options: BuildOptions) -> str:
        return content_key(
            "approved-build-plan",
            {
                "chapters": [
                    {
                        "index": chapter.index,
                        "title": chapter.title,
                        "text_sha256": sha256_text(chapter.text),
                    }
                    for chapter in chapters
                ],
                "speaker_mode": options.speaker_mode,
                "force": options.force,
                "openai": {
                    "base_url": self.config.base_url,
                    "tts_model": self.config.tts_model,
                    "llm_model": self.config.llm_model,
                    "default_voice": self.config.default_voice,
                    "response_format": self.config.response_format,
                    "speed": self.config.speed,
                    "max_input_chars": self.config.max_input_chars,
                },
                "voices": self.voice_config.model_dump(mode="json"),
            },
        )

    def _build_chapter(
        self,
        chapter: Chapter,
        output_dir: Path,
        allocator: SpeakerAllocator,
        tts: Any,
        *,
        force: bool,
    ) -> tuple[ChapterBuildReport, ChapterManifest]:
        lines, _ = allocator.allocate(chapter.text)
        wav_parts: list[Path] = []
        cache_keys: list[str] = []
        voices: set[str] = set()
        for line in lines:
            for part in chunk_text(line.text, self.config.max_input_chars):
                result = tts.synthesize(
                    part,
                    voice=line.voice,
                    instructions=line.instructions,
                    force=force,
                )
                synthesis = _coerce_synthesis_result(result, tts, part, line)
                wav_parts.append(synthesis.path)
                cache_keys.append(synthesis.cache_key)
                if line.voice:
                    voices.add(line.voice)

        if not wav_parts:
            raise BuildError(f"Chapter {chapter.index} produced no audio segments.")
        basename = f"{chapter.index:04d}-{safe_filename_component(chapter.title)}"
        audio_path = output_dir / "audio" / f"{basename}.wav"
        manifest_path = output_dir / "manifests" / f"{basename}.json"
        merge_wav_files(wav_parts, audio_path)
        manifest = ChapterManifest(
            schema_version=1,
            chapter_index=chapter.index,
            title=chapter.title,
            audio_file=audio_path.relative_to(output_dir).as_posix(),
            character_count=len(chapter.text),
            sha256=sha256_text(chapter.text),
            voices=sorted(voices),
            cache_keys=cache_keys,
            ai_generated=True,
        )
        atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
        return (
            ChapterBuildReport(
                index=chapter.index,
                audio_path=audio_path,
                manifest_path=manifest_path,
            ),
            manifest,
        )

    @staticmethod
    def _load_selected_chapters(
        input_dir: str | Path,
        options: BuildOptions,
    ) -> tuple[BookSpec, list[Chapter]]:
        try:
            return load_book_directory(
                input_dir,
                chapter_indexes=options.chapter_indexes,
                max_chapters=options.max_chapters,
                max_characters=options.max_tts_characters,
            )
        except BookSelectionError as exc:
            raise InputError(str(exc)) from exc


def parse_chapter_selection(
    value: str | None,
    *,
    max_items: int = ABSOLUTE_MAX_CHAPTERS,
) -> frozenset[int] | None:
    """Parse ``1,3-5`` into positive chapter indexes."""

    if value is None or not value.strip():
        return None
    if max_items <= 0 or max_items > ABSOLUTE_MAX_CHAPTERS:
        raise InputError(f"chapter selection limit must be between 1 and {ABSOLUTE_MAX_CHAPTERS}")
    selected: set[int] = set()
    try:
        for token in value.split(","):
            token = token.strip()
            if not token:
                raise ValueError
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start, end = int(start_text), int(end_text)
                if start <= 0 or end < start:
                    raise ValueError
                for index in range(start, end + 1):
                    if index not in selected and len(selected) >= max_items:
                        raise InputError(
                            f"--chapters must not select more than {max_items} indexes."
                        )
                    selected.add(index)
            else:
                index = int(token)
                if index <= 0:
                    raise ValueError
                if index not in selected and len(selected) >= max_items:
                    raise InputError(f"--chapters must not select more than {max_items} indexes.")
                selected.add(index)
    except InputError:
        raise
    except ValueError as exc:
        raise InputError("--chapters must look like 1,3-5 and contain positive indexes.") from exc
    return frozenset(selected)


def _load_voices(path: str | Path | None) -> VoiceConfig:
    if path is not None:
        return load_voice_config(path)
    default_resource = resources.files("audiobook_generator.data").joinpath("voices.default.json")
    with resources.as_file(default_resource) as default_path:
        return load_voice_config(default_path)


def _adjacent_narration(items: list[tuple[str, str]], index: int, direction: int) -> str:
    position = index + direction
    while 0 <= position < len(items):
        kind, text = items[position]
        if kind == "narration":
            return text
        position += direction
    return ""


def _safe_cache_probe(llm: Any, previous: str, quote: str, following: str) -> bool:
    try:
        return bool(llm.is_cached(previous, quote, following))
    except (AttributeError, OSError, ValueError):
        return False


def _safe_tts_cache_probe(tts: Any, text: str, voice: str | None, instructions: str) -> bool:
    try:
        return bool(tts.is_cached(text, voice=voice, instructions=instructions))
    except (AttributeError, OSError, ValueError):
        return False


def _coerce_synthesis_result(
    result: Any,
    tts: Any,
    text: str,
    line: Any,
) -> SynthesisResult:
    if isinstance(result, SynthesisResult):
        return result
    if isinstance(result, (str, Path)):
        try:
            key = tts.cache_key(text, voice=line.voice, instructions=line.instructions)
        except AttributeError:
            key = sha256_text(f"{line.voice}\0{line.instructions}\0{text}")
        return SynthesisResult(path=Path(result), cache_key=key, cache_hit=False)
    if hasattr(result, "path") and hasattr(result, "cache_key"):
        return SynthesisResult(
            path=Path(result.path),
            cache_key=str(result.cache_key),
            cache_hit=bool(getattr(result, "cache_hit", False)),
        )
    raise BuildError("TTS client returned an invalid synthesis result.")
