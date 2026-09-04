"""Speaker inference through the OpenAI Responses API."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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

from .cache import atomic_write_json, content_key, load_json_cache
from .config import OpenAIConfig
from .errors import APIConfigurationError, RecoverableAPIError

SPEAKER_PROMPT_VERSION = 1

_SPEAKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "speaker": {"type": ["string", "null"]},
        "gender": {"enum": ["male", "female", None]},
        "tone": {"type": ["string", "null"]},
    },
    "required": ["speaker", "gender", "tone"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class SpeakerInference:
    speaker: str | None = None
    gender: str | None = None
    tone: str | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> SpeakerInference:
        if not isinstance(value, dict):
            raise ValueError("speaker result must be an object")
        speaker = value.get("speaker")
        gender = value.get("gender")
        tone = value.get("tone")
        if speaker is not None and not isinstance(speaker, str):
            raise ValueError("speaker must be a string or null")
        if gender not in {None, "male", "female"}:
            raise ValueError("gender must be male, female, or null")
        if tone is not None and not isinstance(tone, str):
            raise ValueError("tone must be a string or null")
        return cls(
            speaker=_clean_optional(speaker),
            gender=gender,
            tone=_clean_optional(tone),
        )


class OpenAILLMClient:
    """Infer dialogue speakers, with a content-addressed metadata-only cache."""

    def __init__(
        self,
        config: OpenAIConfig,
        *,
        cache_dir: str | Path | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.client = client

    def cache_key(self, previous_narration: str, quote: str, next_narration: str) -> str:
        return content_key(
            "speaker-inference",
            {
                "prompt_version": SPEAKER_PROMPT_VERSION,
                "base_url": self.config.base_url,
                "model": self.config.llm_model,
                "previous_narration": previous_narration,
                "quote": quote,
                "next_narration": next_narration,
            },
        )

    def is_cached(self, previous_narration: str, quote: str, next_narration: str) -> bool:
        key = self.cache_key(previous_narration, quote, next_narration)
        return self._read_cache(key) is not None

    def infer_speaker(
        self, previous_narration: str, quote: str, next_narration: str
    ) -> SpeakerInference:
        key = self.cache_key(previous_narration, quote, next_narration)
        if cached := self._read_cache(key):
            return cached

        user_content = json.dumps(
            {
                "previous_narration": previous_narration,
                "quote": quote,
                "next_narration": next_narration,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            response = self._get_client().responses.create(
                model=self.config.llm_model,
                instructions=(
                    "Identify who speaks the quoted line from the surrounding narration. "
                    "Use null when the speaker, gender, or tone cannot be established. "
                    "Do not invent a named person."
                ),
                input=user_content,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "speaker_inference",
                        "strict": True,
                        "schema": _SPEAKER_SCHEMA,
                    }
                },
                store=False,
            )
            result = SpeakerInference.from_mapping(json.loads(response.output_text))
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise APIConfigurationError(
                "OpenAI authentication or permission was rejected."
            ) from exc
        except (BadRequestError, NotFoundError) as exc:
            raise APIConfigurationError(
                "OpenAI model, endpoint, or request configuration was rejected."
            ) from exc
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise RecoverableAPIError("Speaker inference is temporarily unavailable.") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise RecoverableAPIError("Speaker inference is temporarily unavailable.") from exc
            raise APIConfigurationError("OpenAI rejected the speaker inference request.") from exc
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RecoverableAPIError(
                "Speaker inference returned an invalid structured result."
            ) from exc

        self._write_cache(key, result)
        return result

    def _get_client(self) -> Any:
        if self.client is None:
            if not self.config.api_key:
                raise APIConfigurationError("OPENAI_API_KEY is required for LLM speaker inference.")
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                max_retries=3,
                timeout=180.0,
            )
        return self.client

    def _cache_path(self, key: str) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> SpeakerInference | None:
        path = self._cache_path(key)
        if path is None:
            return None
        value = load_json_cache(path)
        try:
            if not isinstance(value, dict) or value.get("schema_version") != 1:
                return None
            return SpeakerInference.from_mapping(value.get("result"))
        except ValueError:
            return None

    def _write_cache(self, key: str, result: SpeakerInference) -> None:
        path = self._cache_path(key)
        if path is not None:
            atomic_write_json(path, {"schema_version": 1, "result": asdict(result)})


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned[:100] if cleaned else None
