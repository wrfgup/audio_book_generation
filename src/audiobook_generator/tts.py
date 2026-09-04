"""OpenAI Speech API adapter with validated, content-addressed WAV caching."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from .audio import inspect_wav
from .cache import content_key
from .config import OpenAIConfig
from .errors import APIConfigurationError, APIRequestError, BuildError

TTS_CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    path: Path
    cache_key: str
    cache_hit: bool


class OpenAITTSClient:
    """Synthesize WAV files through the official OpenAI Python SDK."""

    def __init__(
        self,
        config: OpenAIConfig,
        *,
        cache_dir: str | Path,
        client: Any | None = None,
    ) -> None:
        if config.response_format != "wav":
            raise APIConfigurationError("Version 1 supports WAV output only.")
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.client = client

    def cache_key(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str = "",
    ) -> str:
        return content_key(
            "openai-tts",
            {
                "tts_cache_version": TTS_CACHE_VERSION,
                "base_url": self.config.base_url,
                "text": text,
                "model": self.config.tts_model,
                "voice": voice or self.config.default_voice,
                "instructions": instructions,
                "speed": self.config.speed,
                "response_format": self.config.response_format,
            },
        )

    def cache_path(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str = "",
    ) -> Path:
        key = self.cache_key(text, voice=voice, instructions=instructions)
        return self.cache_dir / f"{key}.wav"

    def is_cached(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str = "",
    ) -> bool:
        path = self.cache_path(text, voice=voice, instructions=instructions)
        return _is_valid_wav(path)

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str = "",
        force: bool = False,
    ) -> SynthesisResult:
        if not text.strip():
            raise BuildError("Cannot synthesize empty text.")

        selected_voice = voice or self.config.default_voice
        key = self.cache_key(text, voice=selected_voice, instructions=instructions)
        cached_path = self.cache_dir / f"{key}.wav"
        if not force and _is_valid_wav(cached_path):
            return SynthesisResult(cached_path, key, True)

        cached_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=cached_path.parent,
            prefix=f".{key}.",
            suffix=".tmp.wav",
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with self._get_client().audio.speech.with_streaming_response.create(
                model=self.config.tts_model,
                voice=selected_voice,
                input=text,
                instructions=instructions,
                response_format="wav",
                speed=self.config.speed,
            ) as response:
                response.stream_to_file(temporary)
            inspect_wav(temporary)
            os.replace(temporary, cached_path)
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise APIConfigurationError(
                "OpenAI authentication or permission was rejected."
            ) from exc
        except (BadRequestError, NotFoundError) as exc:
            raise APIConfigurationError(
                "OpenAI model, endpoint, voice, or request configuration was rejected."
            ) from exc
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise APIRequestError("OpenAI audio synthesis is temporarily unavailable.") from exc
        except APIStatusError as exc:
            if 400 <= exc.status_code < 500:
                raise APIConfigurationError("OpenAI rejected the audio synthesis request.") from exc
            raise APIRequestError("OpenAI audio synthesis is temporarily unavailable.") from exc
        except (OSError, BuildError) as exc:
            raise BuildError("Audio synthesis did not produce a valid WAV file.") from exc
        finally:
            temporary.unlink(missing_ok=True)

        return SynthesisResult(cached_path, key, False)

    def _get_client(self) -> Any:
        if self.client is None:
            if not self.config.api_key:
                raise APIConfigurationError("OPENAI_API_KEY is required to synthesize audio.")
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                max_retries=3,
                timeout=600.0,
            )
        return self.client

    def synthesize_to_file(
        self,
        text: str,
        output_path: str | Path,
        *,
        voice: str | None = None,
        instructions: str = "",
        force: bool = False,
    ) -> Path:
        """Synthesize to cache, then atomically materialize the requested path."""

        result = self.synthesize(
            text,
            voice=voice,
            instructions=instructions,
            force=force,
        )
        destination = Path(output_path)
        if result.path.resolve() == destination.resolve():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        try:
            with result.path.open("rb") as source, os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            inspect_wav(temporary_name)
            os.replace(temporary_name, destination)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return destination


def _is_valid_wav(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        inspect_wav(path)
    except BuildError:
        return False
    return True
