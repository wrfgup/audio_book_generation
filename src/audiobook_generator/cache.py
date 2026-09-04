"""Small content-addressed cache helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CACHE_FORMAT_VERSION = 1


def sha256_text(value: str) -> str:
    """Return a stable SHA-256 digest for UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def content_key(namespace: str, payload: Mapping[str, Any]) -> str:
    """Hash canonical JSON with an explicit cache namespace and format version."""

    material = {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "namespace": namespace,
        "payload": payload,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    """Write bytes beside the destination and atomically replace it."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def atomic_write_json(path: str | Path, value: Any) -> Path:
    """Serialize JSON predictably and replace the destination atomically."""

    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return atomic_write_bytes(path, data)


def load_json_cache(path: str | Path) -> Any | None:
    """Return cached JSON or ``None`` when it is absent or corrupt."""

    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
