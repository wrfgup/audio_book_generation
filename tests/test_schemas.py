from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from audiobook_generator.config import OpenAIConfig, load_voice_config
from audiobook_generator.io_utils import SchemaError, validate_document
from audiobook_generator.models import (
    BookManifestChapter,
    BookSpec,
    ChapterManifest,
    SiteConfig,
    VoiceConfig,
)
from audiobook_generator.sources import SourceSecurityError, load_site_config


def valid_book_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {"type": "local_text"},
        "book": {"title": "Synthetic example", "author": None},
        "chapters": [
            {
                "index": 1,
                "title": "Chapter one",
                "file": "chapters/0001-Chapter one.txt",
                "source_url": None,
            }
        ],
    }


def valid_site_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "start_url": "https://example.org/book",
        "allowed_domains": ["example.org"],
        "selectors": {
            "book_title": "h1",
            "chapter_links": ".chapters a",
            "chapter_content": "article",
        },
    }


def valid_voice_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "narrator": {"voice": "alloy", "instructions": "Read naturally."},
        "male": [],
        "female": [],
        "characters": {},
        "default_dialogue": None,
    }


@pytest.mark.parametrize(
    "model,data",
    [
        (BookSpec, valid_book_data()),
        (SiteConfig, valid_site_data()),
        (VoiceConfig, valid_voice_data()),
    ],
)
def test_versioned_schemas_accept_version_one(model: object, data: dict[str, object]) -> None:
    validated = model.model_validate(data)  # type: ignore[attr-defined]

    assert validated.schema_version == 1


@pytest.mark.parametrize(
    "data_factory,model",
    [(valid_book_data, BookSpec), (valid_site_data, SiteConfig), (valid_voice_data, VoiceConfig)],
)
def test_version_is_required_and_must_be_one(data_factory: object, model: object) -> None:
    data = data_factory()  # type: ignore[operator]
    del data["schema_version"]
    with pytest.raises(ValidationError):
        model.model_validate(data)  # type: ignore[attr-defined]
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        model.model_validate(data)  # type: ignore[attr-defined]


def test_unknown_schema_fields_are_rejected() -> None:
    data = valid_site_data()
    data["headers"] = {"Authorization": "secret"}

    with pytest.raises(ValidationError):
        SiteConfig.model_validate(data)


@pytest.mark.parametrize(
    "chapter_path",
    [
        "../outside.txt",
        "chapters/../outside.txt",
        "/chapters/one.txt",
        "C:/chapters/one.txt",
        "chapters\\one.txt",
        "chapters/nested/one.txt",
        "chapters/one.md",
    ],
)
def test_book_schema_rejects_unsafe_chapter_paths(chapter_path: str) -> None:
    data = valid_book_data()
    data["chapters"][0]["file"] = chapter_path  # type: ignore[index]

    with pytest.raises(ValidationError):
        BookSpec.model_validate(data)


@pytest.mark.parametrize("duplicate_field", ["index", "file"])
def test_book_schema_rejects_duplicate_chapters(duplicate_field: str) -> None:
    data = valid_book_data()
    second = dict(data["chapters"][0])  # type: ignore[index]
    second["title"] = "Another"
    if duplicate_field == "index":
        second["file"] = "chapters/0002-Another.txt"
    else:
        second["index"] = 2
    data["chapters"].append(second)  # type: ignore[union-attr]

    with pytest.raises(ValidationError):
        BookSpec.model_validate(data)


def test_recorded_source_urls_must_be_https_and_query_free() -> None:
    data = valid_book_data()
    data["source"] = {"type": "web", "url": "https://user:pass@example.org/book"}

    with pytest.raises(ValidationError):
        BookSpec.model_validate(data)


def test_load_voice_config_accepts_utf8_bom(tmp_path) -> None:
    path = tmp_path / "voices.json"
    path.write_text(json.dumps(valid_voice_data()), encoding="utf-8-sig")

    assert load_voice_config(path).narrator.voice == "alloy"


def test_site_loader_validates_security_without_dns_or_network(tmp_path) -> None:
    path = tmp_path / "site.json"
    path.write_text(json.dumps(valid_site_data()), encoding="utf-8")

    assert load_site_config(path).start_url == "https://example.org/book"


@pytest.mark.parametrize(
    ("start_url", "domains"),
    [
        ("http://example.org/book", ["example.org"]),
        ("https://user:pass@example.org/book", ["example.org"]),
        ("https://sub.example.org/book", ["example.org"]),
        ("https://127.0.0.1/book", ["127.0.0.1"]),
        ("https://localhost/book", ["localhost"]),
    ],
)
def test_site_loader_rejects_unsafe_urls(tmp_path, start_url: str, domains: list[str]) -> None:
    data = valid_site_data()
    data["start_url"] = start_url
    data["allowed_domains"] = domains
    path = tmp_path / "site.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SourceSecurityError):
        load_site_config(path)


def test_site_interval_has_a_half_second_minimum() -> None:
    data = valid_site_data()
    data["request_interval_seconds"] = 0.49

    with pytest.raises(ValidationError):
        SiteConfig.model_validate(data)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.org/v1",
        "ftp://api.example.org/v1",
        "https://user:pass@api.example.org/v1",
        "https://api.example.org/v1?token=x",
        "https://api.example.org/v1#fragment",
    ],
)
def test_openai_config_rejects_unsafe_base_urls_without_echoing_them(base_url: str) -> None:
    with pytest.raises(ValidationError) as captured:
        OpenAIConfig(base_url=base_url)

    assert base_url not in str(captured.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://compatible.example.org/v1",
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_openai_config_accepts_https_and_loopback_http(base_url: str) -> None:
    assert OpenAIConfig(base_url=base_url).base_url == base_url


def test_openai_api_key_is_hidden_from_repr() -> None:
    assert "super-secret" not in repr(OpenAIConfig(api_key="super-secret"))


def test_manifest_paths_and_cache_keys_are_validated() -> None:
    digest = "a" * 64
    chapter = ChapterManifest(
        schema_version=1,
        chapter_index=1,
        title="One",
        audio_file="audio/one.wav",
        character_count=10,
        sha256=digest,
        cache_keys=[digest],
    )
    entry = BookManifestChapter(
        index=1,
        title="One",
        audio_file="audio/one.wav",
        manifest_file="manifests/one.json",
        character_count=10,
        sha256=digest,
    )

    assert chapter.ai_generated is True
    assert entry.manifest_file == "manifests/one.json"
    with pytest.raises(ValidationError):
        chapter.model_copy(update={"cache_keys": ["not-a-digest"]}).model_validate(
            {**chapter.model_dump(), "cache_keys": ["not-a-digest"]}
        )
    with pytest.raises(ValidationError):
        BookManifestChapter(**{**entry.model_dump(), "audio_file": "../outside.wav"})


def test_safe_schema_error_does_not_echo_input() -> None:
    data = valid_book_data()
    data["book"] = {"title": "PRIVATE-CONTENT", "unexpected": True}

    with pytest.raises(SchemaError) as captured:
        validate_document(BookSpec, data)

    assert "PRIVATE-CONTENT" not in str(captured.value)
