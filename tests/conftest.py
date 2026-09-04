from __future__ import annotations

import wave
from pathlib import Path


def write_test_wav(
    path: Path,
    *,
    frames: int = 16,
    channels: int = 1,
    sample_width: int = 2,
    frame_rate: int = 16_000,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\x00" * (channels * sample_width)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(sample_width)
        stream.setframerate(frame_rate)
        stream.writeframes(frame * frames)
    return path
