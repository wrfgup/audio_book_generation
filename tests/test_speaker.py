from __future__ import annotations

from dataclasses import dataclass

import pytest

from audiobook_generator.errors import RecoverableAPIError
from audiobook_generator.llm import SpeakerInference
from audiobook_generator.models import VoiceConfig, VoiceStyleSpec
from audiobook_generator.speaker import SpeakerAllocator, VoiceRegistry


def voice_config() -> VoiceConfig:
    return VoiceConfig(
        schema_version=1,
        narrator=VoiceStyleSpec(voice="narrator"),
        male=[VoiceStyleSpec(voice="male-a"), VoiceStyleSpec(voice="male-b")],
        female=[VoiceStyleSpec(voice="female-a"), VoiceStyleSpec(voice="female-b")],
        characters={},
        default_dialogue=None,
    )


def test_voice_assignment_is_deterministic() -> None:
    registry = VoiceRegistry.from_config(voice_config())
    first, _ = SpeakerAllocator(registry, mode="rules").allocate("李明说道：“你好。”")
    second, _ = SpeakerAllocator(registry, mode="rules").allocate("李明说道：“你好。”")
    first_voice = next(line.voice for line in first if line.kind == "dialogue")
    second_voice = next(line.voice for line in second if line.kind == "dialogue")
    assert first_voice == second_voice
    assert first_voice in {"male-a", "male-b", "female-a", "female-b"}


def test_explicit_character_and_default_dialogue_win() -> None:
    config = voice_config().model_copy(
        update={
            "characters": {"小禾": VoiceStyleSpec(voice="custom")},
            "default_dialogue": VoiceStyleSpec(voice="default"),
        }
    )
    registry = VoiceRegistry.from_config(config)
    lines, mapping = SpeakerAllocator(registry, mode="rules").allocate("小禾说道：“早上好。”")
    dialogue = next(line for line in lines if line.kind == "dialogue")
    assert dialogue.voice == "custom"
    assert mapping["小禾"]["voice"] == "custom"


@dataclass
class FailingLLM:
    calls: int = 0

    def infer_speaker(self, previous: str, quote: str, following: str) -> SpeakerInference:
        self.calls += 1
        raise RecoverableAPIError("temporary")


def test_auto_warns_once_and_falls_back_to_rules() -> None:
    messages: list[str] = []
    llm = FailingLLM()
    allocator = SpeakerAllocator(
        VoiceRegistry.from_config(voice_config()),
        llm_client=llm,  # type: ignore[arg-type]
        mode="auto",
        warning_handler=messages.append,
    )
    lines, _ = allocator.allocate("甲说道：“一。”乙说道：“二。”")
    assert len([line for line in lines if line.kind == "dialogue"]) == 2
    assert llm.calls == 2
    assert messages == ["LLM speaker inference failed; falling back to local rules."]


def test_llm_mode_does_not_hide_recoverable_failure() -> None:
    allocator = SpeakerAllocator(
        VoiceRegistry.from_config(voice_config()),
        llm_client=FailingLLM(),  # type: ignore[arg-type]
        mode="llm",
    )
    with pytest.raises(RecoverableAPIError):
        allocator.allocate("甲说道：“一。”")


def test_llm_mode_requires_client() -> None:
    with pytest.raises(ValueError, match="requires"):
        SpeakerAllocator(VoiceRegistry.from_config(voice_config()), mode="llm")
