from __future__ import annotations

import wave
from pathlib import Path

import pytest

import audiobook_generator.audio as audio_module
from audiobook_generator.audio import WavFormat, inspect_wav, merge_wav_files
from audiobook_generator.errors import BuildError
from conftest import write_test_wav


def test_merge_accepts_different_frame_counts_and_streams(tmp_path: Path) -> None:
    first = write_test_wav(tmp_path / "first.wav", frames=7)
    second = write_test_wav(tmp_path / "second.wav", frames=11)

    output = merge_wav_files([first, second], tmp_path / "joined.wav", frames_per_read=3)

    assert inspect_wav(output) == WavFormat(1, 2, 16_000, "NONE")
    with wave.open(str(output), "rb") as stream:
        assert stream.getnframes() == 18


def test_merge_rejects_format_mismatch_without_output(tmp_path: Path) -> None:
    first = write_test_wav(tmp_path / "first.wav", frame_rate=16_000)
    second = write_test_wav(tmp_path / "second.wav", frame_rate=24_000)
    output = tmp_path / "joined.wav"

    with pytest.raises(BuildError, match="format"):
        merge_wav_files([first, second], output)

    assert not output.exists()


@pytest.mark.parametrize("inputs", [[], ()])
def test_merge_rejects_empty_input(inputs: list[Path] | tuple[()]) -> None:
    with pytest.raises(BuildError, match="empty"):
        merge_wav_files(inputs, "unused.wav")


def test_merge_validates_chunk_size(tmp_path: Path) -> None:
    source = write_test_wav(tmp_path / "source.wav")
    with pytest.raises(ValueError, match="positive"):
        merge_wav_files([source], tmp_path / "out.wav", frames_per_read=0)


def test_inspect_rejects_corrupt_wav_without_echoing_data(tmp_path: Path) -> None:
    source = tmp_path / "secret.wav"
    source.write_bytes(b"not-a-wave secret-body")
    with pytest.raises(BuildError, match="Invalid WAV file") as caught:
        inspect_wav(source)
    assert "secret-body" not in str(caught.value)


def test_inspect_rejects_zero_frame_and_truncated_wav(tmp_path: Path) -> None:
    zero = write_test_wav(tmp_path / "zero.wav", frames=0)
    truncated = write_test_wav(tmp_path / "truncated.wav", frames=10)
    truncated.write_bytes(truncated.read_bytes()[:-2])

    with pytest.raises(BuildError, match="no audio frames"):
        inspect_wav(zero)
    with pytest.raises(BuildError, match="truncated"):
        inspect_wav(truncated)


def test_merge_rejects_riff_size_overflow_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_test_wav(tmp_path / "source.wav")
    monkeypatch.setattr(audio_module, "_wav_data_bytes", lambda _path: 0xFFFFFFFF)
    output = tmp_path / "out.wav"
    with pytest.raises(BuildError, match="size limit"):
        merge_wav_files([source], output)
    assert not output.exists()
