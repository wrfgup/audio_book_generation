from __future__ import annotations

from pathlib import Path

from audiobook_generator.cache import (
    atomic_write_bytes,
    atomic_write_json,
    content_key,
    load_json_cache,
    sha256_file,
    sha256_text,
)


def test_content_keys_are_canonical_and_namespaced() -> None:
    left = content_key("one", {"b": 2, "a": "文本"})
    right = content_key("one", {"a": "文本", "b": 2})
    assert left == right
    assert left != content_key("two", {"a": "文本", "b": 2})
    assert len(left) == 64


def test_atomic_writes_and_hashes(tmp_path: Path) -> None:
    binary = atomic_write_bytes(tmp_path / "nested" / "data.bin", b"hello")
    document = atomic_write_json(tmp_path / "cache.json", {"value": 1})
    assert sha256_file(binary) == sha256_text("hello")
    assert load_json_cache(document) == {"value": 1}


def test_corrupt_or_missing_json_cache_is_a_miss(tmp_path: Path) -> None:
    assert load_json_cache(tmp_path / "missing.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    assert load_json_cache(corrupt) is None
