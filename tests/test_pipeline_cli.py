from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from audiobook_generator import cli
from audiobook_generator.cache import content_key
from audiobook_generator.config import OpenAIConfig
from audiobook_generator.errors import InputError
from audiobook_generator.models import VoiceConfig, VoiceStyleSpec
from audiobook_generator.pipeline import (
    AudiobookBuilder,
    BuildOptions,
    parse_chapter_selection,
)
from audiobook_generator.sources import import_text
from audiobook_generator.tts import SynthesisResult
from conftest import write_test_wav


class FakeTTS:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.calls: list[str] = []
        self.fail_on_call: int | None = None

    def cache_key(self, text: str, *, voice: str | None, instructions: str) -> str:
        return content_key(
            "fake-tts",
            {"text": text, "voice": voice, "instructions": instructions},
        )

    def is_cached(self, text: str, *, voice: str | None, instructions: str) -> bool:
        return (
            self.cache_dir / f"{self.cache_key(text, voice=voice, instructions=instructions)}.wav"
        ).is_file()

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None,
        instructions: str,
        force: bool,
    ) -> SynthesisResult:
        key = self.cache_key(text, voice=voice, instructions=instructions)
        path = self.cache_dir / f"{key}.wav"
        if path.is_file() and not force:
            return SynthesisResult(path, key, True)
        self.calls.append(text)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("simulated interruption")
        write_test_wav(path, frames=max(1, len(text)))
        return SynthesisResult(path, key, False)


class PlanningLLM:
    def __init__(self, hit_quote: str) -> None:
        self.hit_quote = hit_quote
        self.inference_calls = 0

    def is_cached(self, previous: str, quote: str, following: str) -> bool:
        return quote == self.hit_quote

    def infer_speaker(self, previous: str, quote: str, following: str):
        self.inference_calls += 1
        raise AssertionError("planning must not infer speakers")


def minimal_voices() -> VoiceConfig:
    return VoiceConfig(
        schema_version=1,
        narrator=VoiceStyleSpec(voice="alloy", instructions="Narrate."),
        male=[VoiceStyleSpec(voice="ash", instructions="Speak.")],
        female=[VoiceStyleSpec(voice="coral", instructions="Speak.")],
        characters={},
        default_dialogue=VoiceStyleSpec(voice="alloy", instructions="Speak."),
    )


def make_book(tmp_path: Path) -> Path:
    source = tmp_path / "story.txt"
    source.write_text(
        "第一章 清晨\n小禾推开窗。她说道：“今天会是晴天。”\n\n第二章 出发\n列车缓缓启动。",
        encoding="utf-8",
    )
    book_dir = tmp_path / "book"
    import_text(source, book_dir, title="自创测试故事", author="示例作者")
    return book_dir


def test_offline_build_writes_privacy_preserving_manifests_and_resumes(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    output = tmp_path / "output"
    fake_tts = FakeTTS(output / ".cache" / "tts")
    builder = AudiobookBuilder(
        OpenAIConfig(max_input_chars=12),
        voice_config=minimal_voices(),
        tts_client=fake_tts,
    )
    options = BuildOptions(speaker_mode="rules")

    before = builder.plan_from_book_dir(book_dir, output, options)
    report = builder.build_from_book_dir(book_dir, output, options)
    calls_after_first_build = len(fake_tts.calls)
    after = builder.plan_from_book_dir(book_dir, output, options)
    builder.build_from_book_dir(book_dir, output, options)

    assert before.tts_cache_hits == 0
    assert after.tts_cache_hits == after.estimated_tts_requests
    assert len(fake_tts.calls) == calls_after_first_build
    assert report.book_manifest_path and report.book_manifest_path.is_file()
    book_manifest = json.loads(report.book_manifest_path.read_text(encoding="utf-8"))
    assert book_manifest["schema_version"] == 1
    assert book_manifest["ai_generated"] is True
    assert all(not Path(item["audio_file"]).is_absolute() for item in book_manifest["chapters"])
    for chapter in report.chapters:
        manifest_text = chapter.manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        assert manifest["ai_generated"] is True
        assert manifest["audio_file"].startswith("audio/")
        assert "今天会是晴天" not in manifest_text
        assert "source_url" not in manifest_text
        assert all(len(key) == 64 for key in manifest["cache_keys"])


def test_interrupted_build_reuses_completed_segment_cache(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    output = tmp_path / "output"
    fake_tts = FakeTTS(output / ".cache" / "tts")
    fake_tts.fail_on_call = 2
    builder = AudiobookBuilder(
        OpenAIConfig(max_input_chars=8),
        voice_config=minimal_voices(),
        tts_client=fake_tts,
    )

    with pytest.raises(RuntimeError, match="interruption"):
        builder.build_from_book_dir(book_dir, output, BuildOptions(speaker_mode="rules"))
    first_key_count = len(list(fake_tts.cache_dir.glob("*.wav")))
    fake_tts.fail_on_call = None
    builder.build_from_book_dir(book_dir, output, BuildOptions(speaker_mode="rules"))

    assert first_key_count == 1
    assert len(list(fake_tts.cache_dir.glob("*.wav"))) > first_key_count


def test_plan_counts_llm_cache_without_making_inference(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    llm = PlanningLLM("今天会是晴天。")
    builder = AudiobookBuilder(
        OpenAIConfig(),
        voice_config=minimal_voices(),
        tts_client=FakeTTS(tmp_path / "cache"),
        llm_client=llm,
    )
    plan = builder.plan_from_book_dir(
        book_dir,
        tmp_path / "output",
        BuildOptions(speaker_mode="auto"),
    )
    assert plan.estimated_llm_requests == 1
    assert plan.llm_cache_hits == 1
    assert llm.inference_calls == 0


def test_auto_plan_never_claims_uncertain_dialogue_tts_cache_hit(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    tts = FakeTTS(tmp_path / "cache")
    rules_builder = AudiobookBuilder(
        OpenAIConfig(),
        voice_config=minimal_voices(),
        tts_client=tts,
    )
    rules_builder.build_from_book_dir(
        book_dir,
        tmp_path / "rules-output",
        BuildOptions(speaker_mode="rules"),
    )
    llm = PlanningLLM("今天会是晴天。")
    auto_builder = AudiobookBuilder(
        OpenAIConfig(),
        voice_config=minimal_voices(),
        tts_client=tts,
        llm_client=llm,
    )

    plan = auto_builder.plan_from_book_dir(
        book_dir,
        tmp_path / "auto-output",
        BuildOptions(speaker_mode="auto"),
    )
    forced_plan = auto_builder.plan_from_book_dir(
        book_dir,
        tmp_path / "auto-output",
        BuildOptions(speaker_mode="auto", force=True),
    )

    assert plan.llm_cache_hits == 1
    assert plan.tts_cache_hits < plan.estimated_tts_requests
    assert plan.paid_tts_requests > 0
    assert forced_plan.llm_cache_hits == 1
    assert forced_plan.tts_cache_hits == 0


def test_approved_plan_rejects_input_or_cache_changes(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    output = tmp_path / "output"
    tts = FakeTTS(output / ".cache" / "tts")
    builder = AudiobookBuilder(
        OpenAIConfig(max_input_chars=12),
        voice_config=minimal_voices(),
        tts_client=tts,
    )
    options = BuildOptions(speaker_mode="rules")
    original_plan = builder.plan_from_book_dir(book_dir, output, options)
    chapter_path = next((book_dir / "chapters").glob("*.txt"))
    original_text = chapter_path.read_text(encoding="utf-8")
    chapter_path.write_text(original_text + "内容已变化。", encoding="utf-8")
    with pytest.raises(InputError, match="inputs changed"):
        builder.build_from_book_dir(book_dir, output, options, approved_plan=original_plan)
    assert not tts.calls

    chapter_path.write_text(original_text, encoding="utf-8")
    builder.build_from_book_dir(book_dir, output, options)
    cached_plan = builder.plan_from_book_dir(book_dir, output, options)
    next(tts.cache_dir.glob("*.wav")).unlink()
    calls_before = len(tts.calls)
    with pytest.raises(InputError, match="Cache state changed"):
        builder.build_from_book_dir(book_dir, output, options, approved_plan=cached_plan)
    assert len(tts.calls) == calls_before


def test_hard_limits_and_chapter_selection_cannot_be_bypassed(tmp_path: Path) -> None:
    book_dir = make_book(tmp_path)
    builder = AudiobookBuilder(
        OpenAIConfig(),
        voice_config=minimal_voices(),
        tts_client=FakeTTS(tmp_path / "cache"),
    )
    with pytest.raises(InputError, match="max-chapters"):
        builder.plan_from_book_dir(
            book_dir,
            tmp_path / "out",
            BuildOptions(speaker_mode="rules", max_chapters=1),
        )
    with pytest.raises(InputError, match="max-tts-characters"):
        builder.plan_from_book_dir(
            book_dir,
            tmp_path / "out",
            BuildOptions(speaker_mode="rules", max_tts_characters=1),
        )
    selected = BuildOptions(
        chapter_indexes=frozenset({2}),
        speaker_mode="rules",
        max_chapters=1,
    )
    assert builder.plan_from_book_dir(book_dir, tmp_path / "out", selected).chapter_count == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("1,3-5", frozenset({1, 3, 4, 5})),
        (" 2 ", frozenset({2})),
    ],
)
def test_parse_chapter_selection(raw: str | None, expected: frozenset[int] | None) -> None:
    assert parse_chapter_selection(raw) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "3-2", "1,,2", "one", "1-2-3"])
def test_parse_chapter_selection_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(InputError):
        parse_chapter_selection(raw)


def test_parse_chapter_selection_bounds_huge_ranges() -> None:
    with pytest.raises(InputError, match="more than 10000"):
        parse_chapter_selection("1-999999999")
    with pytest.raises(InputError, match="between 1 and 10000"):
        parse_chapter_selection("1", max_items=10001)


def test_cli_import_validate_and_keyless_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source = tmp_path / "input.txt"
    source.write_text("这是完全自创的测试内容。", encoding="utf-8")
    book = tmp_path / "book"
    output = tmp_path / "output"

    assert cli.main(["import-text", str(source), "--output", str(book)]) == 0
    assert cli.main(["validate", "--book", str(book)]) == 0
    assert (
        cli.main(
            [
                "build",
                "--input",
                str(book),
                "--output",
                str(output),
                "--speaker-mode",
                "rules",
                "--dry-run",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "no API request was made" in captured.out
    assert not output.exists()


def test_cli_noninteractive_paid_build_requires_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    book = make_book(tmp_path)
    code = cli.main(
        [
            "build",
            "--input",
            str(book),
            "--output",
            str(tmp_path / "output"),
            "--speaker-mode",
            "rules",
        ]
    )
    assert code == 2
    assert "require --yes" in capsys.readouterr().err


def test_cli_returns_two_for_hard_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    book = make_book(tmp_path)
    code = cli.main(
        [
            "build",
            "--input",
            str(book),
            "--output",
            str(tmp_path / "output"),
            "--dry-run",
            "--speaker-mode",
            "rules",
            "--max-tts-characters",
            "1",
            "--yes",
        ]
    )
    assert code == 2
    assert "max-tts-characters" in capsys.readouterr().err


def test_cli_redacts_unexpected_local_path_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_without_leaking(_args: object) -> int:
        raise OSError(r"C:\Users\private-name\secret-book.txt")

    monkeypatch.setattr(cli, "_run_build", fail_without_leaking)
    code = cli.main(["build", "--input", "book", "--output", "output"])
    error = capsys.readouterr().err
    assert code == 1
    assert "private-name" not in error
    assert "secret-book" not in error
    assert "local file operation failed" in error
