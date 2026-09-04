"""Dialogue detection and deterministic voice allocation."""

from __future__ import annotations

import hashlib
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .errors import RecoverableAPIError
from .llm import OpenAILLMClient, SpeakerInference
from .models import DialogueLine, VoiceConfig, VoiceStyle, VoiceStyleSpec
from .text import infer_speaker, split_narration_and_dialogue

SpeakerMode = Literal["auto", "llm", "rules"]


@dataclass(slots=True)
class VoiceRegistry:
    narrator: VoiceStyle
    male: list[VoiceStyle]
    female: list[VoiceStyle]
    characters: dict[str, VoiceStyle]
    default_dialogue: VoiceStyle | None = None

    @classmethod
    def from_config(cls, config: VoiceConfig) -> VoiceRegistry:
        return cls(
            narrator=_to_style(config.narrator),
            male=[_to_style(item) for item in config.male],
            female=[_to_style(item) for item in config.female],
            characters={name: _to_style(item) for name, item in config.characters.items()},
            default_dialogue=(
                _to_style(config.default_dialogue) if config.default_dialogue is not None else None
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceRegistry:
        return cls.from_config(VoiceConfig.model_validate(data))


class SpeakerAllocator:
    """Allocate stable voices while keeping recoverable auto-mode failures optional."""

    def __init__(
        self,
        registry: VoiceRegistry,
        llm_client: OpenAILLMClient | None = None,
        assigned: dict[str, VoiceStyle] | None = None,
        *,
        mode: SpeakerMode = "auto",
        warning_handler: Callable[[str], None] | None = None,
    ) -> None:
        if mode not in {"auto", "llm", "rules"}:
            raise ValueError("speaker mode must be auto, llm, or rules")
        if mode == "llm" and llm_client is None:
            raise ValueError("llm speaker mode requires an LLM client")
        self.registry = registry
        self.llm_client = llm_client
        self.assigned: dict[str, VoiceStyle] = assigned or {}
        self.mode = mode
        self._warn = warning_handler or _default_warning
        self._warned_about_fallback = False

    def allocate(self, chapter_text: str) -> tuple[list[DialogueLine], dict[str, dict[str, Any]]]:
        items = split_narration_and_dialogue(chapter_text)
        lines: list[DialogueLine] = []
        speaker_map: dict[str, dict[str, Any]] = {}
        for index, (kind, text) in enumerate(items):
            if kind == "narration":
                lines.append(
                    DialogueLine(
                        index=index,
                        kind="narration",
                        text=text,
                        speaker=None,
                        voice=self.registry.narrator.voice,
                        instructions=self.registry.narrator.instructions,
                    )
                )
                continue

            previous_narration = _find_adjacent_narration(items, index, -1)
            next_narration = _find_adjacent_narration(items, index, 1)
            inference = self._infer_speaker(previous_narration, text, next_narration)
            style = self._pick_style(inference)
            lines.append(
                DialogueLine(
                    index=index,
                    kind="dialogue",
                    text=text,
                    speaker=inference.speaker,
                    voice=style.voice,
                    instructions=style.instructions,
                    tone=inference.tone,
                )
            )
            if inference.speaker:
                # Runtime-only mapping. Serialized manifests contain voices but not character names.
                speaker_map[inference.speaker] = {
                    "voice": style.voice,
                    "instructions": style.instructions,
                    "gender": inference.gender,
                    "tone": inference.tone,
                }
        return lines, speaker_map

    def export_assignments(self) -> dict[str, dict[str, str]]:
        return {
            name: {"voice": style.voice, "instructions": style.instructions}
            for name, style in sorted(self.assigned.items())
        }

    def _infer_speaker(
        self, previous_narration: str, quote: str, next_narration: str
    ) -> SpeakerInference:
        rule_based = SpeakerInference(
            speaker=infer_speaker(f"{previous_narration} “{quote}” {next_narration}")
        )
        if self.mode == "rules" or self.llm_client is None:
            return rule_based
        try:
            inferred = self.llm_client.infer_speaker(previous_narration, quote, next_narration)
        except RecoverableAPIError:
            if self.mode == "llm":
                raise
            if not self._warned_about_fallback:
                self._warn("LLM speaker inference failed; falling back to local rules.")
                self._warned_about_fallback = True
            return rule_based
        if inferred.speaker or inferred.gender or inferred.tone:
            return inferred
        return rule_based

    def _pick_style(self, inference: SpeakerInference) -> VoiceStyle:
        speaker = inference.speaker
        if speaker and speaker in self.registry.characters:
            return self.registry.characters[speaker]
        if speaker and speaker in self.assigned:
            return self.assigned[speaker]

        if self.registry.default_dialogue is not None:
            style = self.registry.default_dialogue
        else:
            candidates = self._candidate_styles(inference)
            style = _stable_choice(candidates, speaker or "unknown-dialogue")

        if speaker:
            self.assigned[speaker] = style
        return style

    def _candidate_styles(self, inference: SpeakerInference) -> list[VoiceStyle]:
        if inference.gender == "female" and self.registry.female:
            return self.registry.female
        if inference.gender == "male" and self.registry.male:
            return self.registry.male
        if inference.speaker and _looks_female_name(inference.speaker) and self.registry.female:
            return self.registry.female
        combined = [*self.registry.male, *self.registry.female]
        return combined or [self.registry.narrator]


def _to_style(value: VoiceStyleSpec) -> VoiceStyle:
    return VoiceStyle(voice=value.voice, instructions=value.instructions)


def _stable_choice(styles: list[VoiceStyle], identity: str) -> VoiceStyle:
    if not styles:
        raise ValueError("voice style list must not be empty")
    digest = hashlib.sha256(identity.casefold().encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(styles)
    return styles[index]


def _find_adjacent_narration(items: list[tuple[str, str]], index: int, direction: int) -> str:
    position = index + direction
    while 0 <= position < len(items):
        kind, text = items[position]
        if kind == "narration":
            return text
        position += direction
    return ""


def _looks_female_name(name: str) -> bool:
    female_hints = ("姐", "妹", "妈", "太太", "夫人", "姑娘", "女士", "阿姨")
    return any(hint in name for hint in female_hints)


def _default_warning(message: str) -> None:
    warnings.warn(message, RuntimeWarning, stacklevel=3)
