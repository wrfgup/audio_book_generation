"""Environment and versioned JSON configuration loading."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .io_utils import atomic_write_json, read_json_object, validate_document
from .models import VoiceConfig


class OpenAIConfig(BaseModel):
    """Validated OpenAI settings.

    ``api_key`` may be empty so import, validation, and dry-run operations work
    without credentials. Paid operations are responsible for requiring it.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    api_key: str = Field(default="", repr=False)
    base_url: str = "https://api.openai.com/v1"
    tts_model: str = Field(default="gpt-4o-mini-tts", min_length=1)
    llm_model: str = Field(default="gpt-5.6-luna", min_length=1)
    default_voice: str = Field(default="alloy", min_length=1)
    response_format: Literal["wav"] = "wav"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    max_input_chars: int = Field(default=850, ge=1, le=100_000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if any(ord(character) <= 0x20 for character in value) or "\\" in value:
            raise ValueError("base URL contains invalid characters")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base URL must not contain a query or fragment")
        if parsed.scheme == "http" and not _is_loopback_hostname(parsed.hostname):
            raise ValueError("HTTP base URLs are allowed only for loopback hosts")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("base URL contains an invalid port") from exc
        return value.rstrip("/")

    @property
    def model(self) -> str:
        """Compatibility alias for the original TTS client."""

        return self.tts_model

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> OpenAIConfig:
        load_dotenv(dotenv_path=env_file, override=False)
        values: dict[str, Any] = {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "tts_model": os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            "llm_model": os.getenv("OPENAI_LLM_MODEL", "gpt-5.6-luna"),
            "default_voice": os.getenv("OPENAI_TTS_VOICE", "alloy"),
            "response_format": os.getenv("OPENAI_TTS_FORMAT", "wav"),
            "speed": os.getenv("OPENAI_TTS_SPEED", "1.0"),
            "max_input_chars": os.getenv("OPENAI_MAX_INPUT_CHARS", "850"),
        }
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            raise ValueError("OpenAI environment configuration is invalid") from exc


OpenAITTSConfig = OpenAIConfig


def _is_loopback_hostname(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def load_env_config(env_file: str | Path | None = None) -> OpenAIConfig:
    """Compatibility wrapper for older callers."""

    return OpenAIConfig.from_env(env_file)


def load_voice_config(path: str | Path) -> VoiceConfig:
    return validate_document(VoiceConfig, read_json_object(path))


def load_json(path: str | Path) -> dict[str, Any]:
    """Compatibility JSON loader with BOM and size handling."""

    return read_json_object(path)


def dump_json(path: str | Path, data: BaseModel | dict[str, Any]) -> None:
    """Compatibility JSON writer using atomic replacement."""

    atomic_write_json(path, data)
