from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobook_generator.config import OpenAIConfig
from audiobook_generator.errors import RecoverableAPIError
from audiobook_generator.llm import OpenAILLMClient, SpeakerInference
from audiobook_generator.tts import OpenAITTSClient
from conftest import write_test_wav


class FakeSpeechResponse:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.corrupt = corrupt

    def __enter__(self) -> FakeSpeechResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def stream_to_file(self, path: str | Path) -> None:
        destination = Path(path)
        if self.corrupt:
            destination.write_bytes(b"corrupt")
        else:
            write_test_wav(destination, frames=9)


class FakeSpeech:
    def __init__(self) -> None:
        self.with_streaming_response = self
        self.calls: list[dict[str, object]] = []
        self.corrupt = False

    def create(self, **kwargs: object) -> FakeSpeechResponse:
        self.calls.append(kwargs)
        return FakeSpeechResponse(corrupt=self.corrupt)


class FakeOpenAI:
    def __init__(self) -> None:
        self.speech = FakeSpeech()
        self.audio = SimpleNamespace(speech=self.speech)
        self.responses = FakeResponses()


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.output = {"speaker": "小禾", "gender": "female", "tone": "calm"}

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.output, ensure_ascii=False))


def test_tts_uses_streaming_sdk_and_validated_cache(tmp_path: Path) -> None:
    sdk = FakeOpenAI()
    config = OpenAIConfig(api_key="test", speed=1.1)
    client = OpenAITTSClient(config, cache_dir=tmp_path / "cache", client=sdk)

    first = client.synthesize("自创测试文本", voice="alloy", instructions="Neutral")
    second = client.synthesize("自创测试文本", voice="alloy", instructions="Neutral")

    assert not first.cache_hit
    assert second.cache_hit
    assert first.path == second.path
    assert len(sdk.speech.calls) == 1
    assert sdk.speech.calls[0] == {
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "input": "自创测试文本",
        "instructions": "Neutral",
        "response_format": "wav",
        "speed": 1.1,
    }


def test_tts_rebuilds_corrupt_cache_and_materializes_atomically(tmp_path: Path) -> None:
    sdk = FakeOpenAI()
    client = OpenAITTSClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path / "cache", client=sdk)
    cached = client.synthesize("hello")
    cached.path.write_bytes(b"broken")

    output = client.synthesize_to_file("hello", tmp_path / "chapter.wav")

    assert output.is_file()
    assert len(sdk.speech.calls) == 2
    assert not list(tmp_path.rglob("*.tmp"))


def test_tts_rejects_empty_or_non_wav_configuration(tmp_path: Path) -> None:
    client = OpenAITTSClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=FakeOpenAI())
    with pytest.raises(Exception, match="empty"):
        client.synthesize("  ")
    with pytest.raises(ValueError):
        OpenAIConfig(response_format="mp3")  # type: ignore[arg-type]


def test_tts_invalid_download_does_not_poison_cache(tmp_path: Path) -> None:
    sdk = FakeOpenAI()
    sdk.speech.corrupt = True
    client = OpenAITTSClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=sdk)
    with pytest.raises(Exception, match="valid WAV"):
        client.synthesize("hello")
    assert not list(tmp_path.glob("*.wav"))


def test_forced_failed_download_preserves_last_valid_cache(tmp_path: Path) -> None:
    sdk = FakeOpenAI()
    client = OpenAITTSClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=sdk)
    cached = client.synthesize("hello")
    original = cached.path.read_bytes()
    sdk.speech.corrupt = True

    with pytest.raises(Exception, match="valid WAV"):
        client.synthesize("hello", force=True)

    assert cached.path.read_bytes() == original
    assert client.is_cached("hello")


def test_responses_api_uses_strict_schema_store_false_and_metadata_only_cache(
    tmp_path: Path,
) -> None:
    sdk = FakeOpenAI()
    client = OpenAILLMClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=sdk)

    first = client.infer_speaker("小禾看向窗外。", "天亮了", "她轻声说道。")
    second = client.infer_speaker("小禾看向窗外。", "天亮了", "她轻声说道。")

    assert first == second == SpeakerInference("小禾", "female", "calm")
    assert len(sdk.responses.calls) == 1
    call = sdk.responses.calls[0]
    assert call["store"] is False
    assert call["text"]["format"]["strict"] is True  # type: ignore[index]
    cache_text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "天亮了" not in cache_text
    assert "previous_narration" not in cache_text


def test_invalid_structured_result_is_recoverable(tmp_path: Path) -> None:
    sdk = FakeOpenAI()
    sdk.responses.output = {"speaker": 123, "gender": "unknown", "tone": None}
    client = OpenAILLMClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=sdk)
    with pytest.raises(RecoverableAPIError, match="invalid structured"):
        client.infer_speaker("before", "quote", "after")


def test_speaker_inference_validation_and_corrupt_cache(tmp_path: Path) -> None:
    assert (
        SpeakerInference.from_mapping({"speaker": " ", "gender": None, "tone": " "})
        == SpeakerInference()
    )
    with pytest.raises(ValueError):
        SpeakerInference.from_mapping([])
    sdk = FakeOpenAI()
    client = OpenAILLMClient(OpenAIConfig(api_key="test"), cache_dir=tmp_path, client=sdk)
    key = client.cache_key("a", "b", "c")
    (tmp_path / f"{key}.json").write_text("{", encoding="utf-8")
    assert client.infer_speaker("a", "b", "c").speaker == "小禾"
    assert len(sdk.responses.calls) == 1
