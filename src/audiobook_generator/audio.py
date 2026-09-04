"""WAV validation and memory-bounded concatenation."""

from __future__ import annotations

import os
import tempfile
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError

MAX_RIFF_DATA_BYTES = 0xFFFFFFFF - 36


@dataclass(frozen=True, slots=True)
class WavFormat:
    channels: int
    sample_width: int
    frame_rate: int
    compression_type: str


def inspect_wav(path: str | Path) -> WavFormat:
    """Validate a WAV file and return the fields required for concatenation."""

    source = Path(path)
    try:
        with wave.open(str(source), "rb") as stream:
            frame_count = stream.getnframes()
            result = WavFormat(
                channels=stream.getnchannels(),
                sample_width=stream.getsampwidth(),
                frame_rate=stream.getframerate(),
                compression_type=stream.getcomptype(),
            )
            if result.channels < 1 or result.sample_width < 1 or result.frame_rate < 1:
                raise BuildError("WAV file has invalid format metadata.")
            if frame_count < 1:
                raise BuildError("WAV file contains no audio frames.")
            expected_bytes = frame_count * result.channels * result.sample_width
            actual_bytes = 0
            while payload := stream.readframes(65_536):
                actual_bytes += len(payload)
            if actual_bytes != expected_bytes:
                raise BuildError("WAV file is truncated or malformed.")
            return result
    except BuildError:
        raise
    except (OSError, EOFError, wave.Error) as exc:
        raise BuildError("Invalid WAV file.") from exc


def merge_wav_files(
    inputs: Iterable[str | Path],
    output_path: str | Path,
    *,
    frames_per_read: int = 65_536,
) -> Path:
    """Concatenate compatible WAV files without retaining a chapter in memory."""

    sources = [Path(item) for item in inputs]
    if not sources:
        raise BuildError("Cannot merge an empty list of WAV files.")
    if frames_per_read <= 0:
        raise ValueError("frames_per_read must be positive")

    expected = inspect_wav(sources[0])
    total_data_bytes = _wav_data_bytes(sources[0])
    for source in sources[1:]:
        if inspect_wav(source) != expected:
            raise BuildError("WAV format does not match the first segment.")
        total_data_bytes += _wav_data_bytes(source)
    if total_data_bytes > MAX_RIFF_DATA_BYTES:
        raise BuildError("Merged audio exceeds the WAV v1 size limit.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp.wav",
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with wave.open(str(temporary), "wb") as merged:
            merged.setnchannels(expected.channels)
            merged.setsampwidth(expected.sample_width)
            merged.setframerate(expected.frame_rate)
            merged.setcomptype(expected.compression_type, "not compressed")
            for source in sources:
                with wave.open(str(source), "rb") as segment:
                    while frames := segment.readframes(frames_per_read):
                        merged.writeframesraw(frames)
        inspect_wav(temporary)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _wav_data_bytes(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as stream:
            return stream.getnframes() * stream.getnchannels() * stream.getsampwidth()
    except (OSError, EOFError, wave.Error) as exc:
        raise BuildError("Invalid WAV file.") from exc
