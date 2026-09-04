"""Small, defensive JSON and file-system helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

DEFAULT_MAX_JSON_BYTES = 5 * 1024 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)


class DataError(ValueError):
    """A safe-to-display input or schema error."""


class SchemaError(DataError):
    """A versioned JSON document did not match its schema."""


def read_json_object(
    path: str | Path, *, max_bytes: int = DEFAULT_MAX_JSON_BYTES
) -> dict[str, Any]:
    """Read one bounded UTF-8/UTF-8-BOM JSON object.

    Error messages intentionally do not echo the path, JSON contents, or parser
    context, as those can contain local usernames, credentials, or book text.
    """

    source = Path(path)
    try:
        if not source.is_file():
            raise DataError("JSON input is not a regular file")
        if source.stat().st_size > max_bytes:
            raise DataError("JSON input exceeds the size limit")
        with source.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except DataError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataError("JSON input could not be read") from exc
    if not isinstance(value, dict):
        raise DataError("JSON document must be an object")
    return value


def validate_document(model: type[ModelT], data: dict[str, Any]) -> ModelT:
    """Validate without including Pydantic's input-value excerpts in errors."""

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        locations = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "document"
                for error in exc.errors(include_url=False, include_input=False)
            }
        )
        summary = ", ".join(locations[:8])
        if len(locations) > 8:
            summary += ", ..."
        raise SchemaError(f"JSON schema validation failed at: {summary}") from exc


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write a text file through a same-directory temporary file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except OSError as exc:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise DataError("output file could not be written") from exc
    return destination


def atomic_write_json(path: str | Path, value: BaseModel | dict[str, Any]) -> Path:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(path, serialized)
