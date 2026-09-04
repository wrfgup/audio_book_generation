"""Runtime objects and versioned public schemas used by the audiobook pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
MAX_CHAPTER_BYTES = 5 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_relative_artifact_path(value: str, *, suffix: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError("artifact path must be a POSIX relative path")
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
        raise ValueError("artifact path must be relative")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("artifact path contains an invalid component")
    if path.suffix.lower() != suffix:
        raise ValueError(f"artifact path must have a {suffix} extension")
    return path.as_posix()


def _validate_recorded_source_url(value: str) -> str:
    if any(ord(character) <= 0x20 for character in value) or "\\" in value:
        raise ValueError("source URL contains invalid characters")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("source URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("recorded source URL must not contain a query or fragment")
    return value


class SchemaModel(BaseModel):
    """Base class for public JSON schemas."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class BookSourceSpec(SchemaModel):
    type: Literal["local_text", "web"]
    url: str | None = None

    @model_validator(mode="after")
    def require_web_url(self) -> BookSourceSpec:
        if self.type == "web" and not self.url:
            raise ValueError("a web source requires a URL")
        if self.type == "local_text" and self.url is not None:
            raise ValueError("a local source must not record a local path or URL")
        if self.url is not None:
            _validate_recorded_source_url(self.url)
        return self


class BookInfo(SchemaModel):
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)


class BookChapterSpec(SchemaModel):
    index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    file: str
    source_url: str | None = None

    @field_validator("file")
    @classmethod
    def validate_chapter_file(cls, value: str) -> str:
        """Require a portable path rooted immediately below ``chapters/``."""

        if not value or "\\" in value or "\x00" in value:
            raise ValueError("chapter file must be a POSIX relative path")
        if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
            raise ValueError("chapter file must be relative")
        path = PurePosixPath(value)
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("chapter file contains an invalid path component")
        if len(path.parts) != 2 or path.parts[0] != "chapters":
            raise ValueError("chapter file must be directly inside chapters/")
        if path.suffix.lower() != ".txt":
            raise ValueError("chapter file must have a .txt extension")
        return path.as_posix()

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _validate_recorded_source_url(value) if value is not None else None


class BookSpec(SchemaModel):
    schema_version: Literal[1]
    source: BookSourceSpec
    book: BookInfo
    chapters: list[BookChapterSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_chapters(self) -> BookSpec:
        indexes = [chapter.index for chapter in self.chapters]
        files = [chapter.file.casefold() for chapter in self.chapters]
        if len(indexes) != len(set(indexes)):
            raise ValueError("chapter indexes must be unique")
        if len(files) != len(set(files)):
            raise ValueError("chapter files must be unique")
        return self


class CSSSelectors(SchemaModel):
    book_title: str = Field(min_length=1, max_length=500)
    chapter_links: str = Field(min_length=1, max_length=500)
    chapter_content: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, min_length=1, max_length=500)
    chapter_title: str | None = Field(default=None, min_length=1, max_length=500)


class SiteConfig(SchemaModel):
    """Configuration for a public, unauthenticated HTML source."""

    schema_version: Literal[1]
    start_url: str
    allowed_domains: list[str] = Field(min_length=1)
    selectors: CSSSelectors
    request_interval_seconds: float = Field(default=0.5, ge=0.5, le=300)
    user_agent: str = Field(
        default="audiobook-generator/0.1 (+https://github.com/)",
        min_length=1,
        max_length=300,
    )
    max_chapters: int | None = Field(default=None, ge=1)

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            domain = value.rstrip(".").lower()
            if domain and domain not in normalized:
                normalized.append(domain)
        if not normalized:
            raise ValueError("allowed_domains must not be empty")
        return normalized


class VoiceStyleSpec(SchemaModel):
    voice: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=2_000)


class VoiceConfig(SchemaModel):
    schema_version: Literal[1]
    narrator: VoiceStyleSpec
    male: list[VoiceStyleSpec] = Field(default_factory=list)
    female: list[VoiceStyleSpec] = Field(default_factory=list)
    characters: dict[str, VoiceStyleSpec] = Field(default_factory=dict)
    default_dialogue: VoiceStyleSpec | None = None

    @field_validator("characters")
    @classmethod
    def reject_blank_character_names(
        cls, values: dict[str, VoiceStyleSpec]
    ) -> dict[str, VoiceStyleSpec]:
        if any(not name.strip() for name in values):
            raise ValueError("character names must not be blank")
        return values


class ChapterManifest(SchemaModel):
    schema_version: Literal[1]
    chapter_index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    audio_file: str
    character_count: int = Field(ge=0)
    sha256: str
    voices: list[str] = Field(default_factory=list)
    cache_keys: list[str] = Field(default_factory=list)
    ai_generated: Literal[True] = True

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("audio_file")
    @classmethod
    def validate_audio_file(cls, value: str) -> str:
        return _validate_relative_artifact_path(value, suffix=".wav")

    @field_validator("cache_keys")
    @classmethod
    def validate_cache_keys(cls, values: list[str]) -> list[str]:
        if any(not _SHA256_RE.fullmatch(value) for value in values):
            raise ValueError("cache keys must be lowercase SHA-256 digests")
        return values


class BookManifestChapter(SchemaModel):
    index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    audio_file: str
    manifest_file: str
    character_count: int = Field(ge=0)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("audio_file")
    @classmethod
    def validate_audio_file(cls, value: str) -> str:
        return _validate_relative_artifact_path(value, suffix=".wav")

    @field_validator("manifest_file")
    @classmethod
    def validate_manifest_file(cls, value: str) -> str:
        return _validate_relative_artifact_path(value, suffix=".json")


class BookManifest(SchemaModel):
    schema_version: Literal[1]
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    chapters: list[BookManifestChapter]
    ai_generated: Literal[True] = True

    @model_validator(mode="after")
    def reject_duplicate_chapters(self) -> BookManifest:
        indexes = [chapter.index for chapter in self.chapters]
        if len(indexes) != len(set(indexes)):
            raise ValueError("chapter indexes must be unique")
        return self


@dataclass(slots=True)
class Chapter:
    index: int
    title: str
    source_url: str | None
    text: str

    def filename(self) -> str:
        from .text import safe_filename_component

        safe_title = safe_filename_component(self.title, fallback=f"chapter-{self.index:04d}")
        return f"{self.index:04d}-{safe_title}.txt"


@dataclass(slots=True)
class VoiceStyle:
    voice: str
    instructions: str = ""


@dataclass(slots=True)
class DialogueLine:
    index: int
    kind: str
    text: str
    speaker: str | None = None
    voice: str | None = None
    instructions: str = ""
    tone: str | None = None
