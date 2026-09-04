from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests

from audiobook_generator.io_utils import DataError, SchemaError
from audiobook_generator.models import MAX_CHAPTER_BYTES, SiteConfig
from audiobook_generator.sources import (
    MAX_HTML_BYTES,
    BookSelectionError,
    GenericHTMLSource,
    SourceNetworkError,
    SourceSecurityError,
    import_text,
    load_book_directory,
)

PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes = b"",
        *,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = body
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size: int) -> list[bytes]:
        del chunk_size
        return self._chunks if self._chunks is not None else [self.content]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, handler: Callable[[str], FakeResponse]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.handler(url)


def site_config(**overrides: Any) -> SiteConfig:
    data: dict[str, Any] = {
        "schema_version": 1,
        "start_url": "https://example.org/book?catalog=1",
        "allowed_domains": ["example.org"],
        "selectors": {
            "book_title": "h1.book",
            "chapter_links": ".chapters a",
            "chapter_content": "article.content",
            "author": ".author",
            "chapter_title": "h1.chapter",
        },
        "request_interval_seconds": 0.5,
    }
    data.update(overrides)
    return SiteConfig.model_validate(data)


def write_book_json(root: Path, chapter_file: str = "chapters/one.txt") -> None:
    value = {
        "schema_version": 1,
        "source": {"type": "local_text"},
        "book": {"title": "Synthetic"},
        "chapters": [{"index": 1, "title": "One", "file": chapter_file}],
    }
    (root / "book.json").write_text(json.dumps(value), encoding="utf-8")


def test_import_text_file_splits_chapters_and_writes_portable_names(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text(
        "第一章 A:B?\n自创内容一。\n第二章 CON\n自创内容二。",
        encoding="utf-8-sig",
    )

    metadata_path = import_text(source, tmp_path / "book", title="Synthetic", author="Tester")
    spec, chapters = load_book_directory(tmp_path / "book")

    assert metadata_path == (tmp_path / "book" / "book.json").resolve()
    assert spec.schema_version == 1
    assert spec.source.type == "local_text"
    assert spec.source.url is None
    assert spec.book.title == "Synthetic"
    assert [chapter.text for chapter in chapters] == ["自创内容一。", "自创内容二。"]
    assert all("\\" not in chapter.file for chapter in spec.chapters)
    assert all(
        not any(character in chapter.file for character in '<>:"|?*') for chapter in spec.chapters
    )


def test_import_text_directory_uses_natural_order_and_single_chapters(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "10.txt").write_text("ten", encoding="utf-8")
    (inputs / "2.TXT").write_text("two", encoding="utf-8-sig")
    (inputs / "ignore.md").write_text("ignored", encoding="utf-8")

    import_text(inputs, tmp_path / "book")
    spec, chapters = load_book_directory(tmp_path / "book")

    assert [chapter.title for chapter in chapters] == ["2", "10"]
    assert [chapter.text for chapter in chapters] == ["two", "ten"]
    assert spec.book.title == "inputs"


def test_import_text_rejects_empty_and_empty_headed_chapters(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("\ufeff \n", encoding="utf-8")
    with pytest.raises(DataError, match="empty"):
        import_text(empty, tmp_path / "empty-book")

    headed = tmp_path / "headed.txt"
    headed.write_text("第一章\n第二章\n正文", encoding="utf-8")
    with pytest.raises(DataError, match="empty"):
        import_text(headed, tmp_path / "headed-book")


@pytest.mark.parametrize(
    "chapter_path",
    ["../outside.txt", "C:/outside.txt", "/outside.txt", "chapters\\one.txt"],
)
def test_load_book_rejects_unsafe_paths(tmp_path: Path, chapter_path: str) -> None:
    root = tmp_path / "book"
    (root / "chapters").mkdir(parents=True)
    (root / "chapters" / "one.txt").write_text("text", encoding="utf-8")
    write_book_json(root, chapter_path)

    with pytest.raises(SchemaError):
        load_book_directory(root)


def test_load_book_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "book"
    chapters = root / "chapters"
    chapters.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    try:
        os.symlink(outside, chapters / "one.txt")
    except OSError:
        pytest.skip("creating symlinks is not available on this host")
    write_book_json(root)

    with pytest.raises(DataError, match="escapes"):
        load_book_directory(root)


def test_load_book_rejects_oversized_and_empty_chapters(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized"
    (oversized / "chapters").mkdir(parents=True)
    (oversized / "chapters" / "one.txt").write_bytes(b"x" * (MAX_CHAPTER_BYTES + 1))
    write_book_json(oversized)
    with pytest.raises(DataError, match="5 MiB"):
        load_book_directory(oversized)

    empty = tmp_path / "empty"
    (empty / "chapters").mkdir(parents=True)
    (empty / "chapters" / "one.txt").write_text(" \n", encoding="utf-8")
    write_book_json(empty)
    with pytest.raises(DataError, match="empty"):
        load_book_directory(empty)


def test_selected_book_load_applies_limits_before_unselected_text(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("第一章\nshort\n第二章\nanother", encoding="utf-8")
    book = tmp_path / "book"
    import_text(source, book)
    chapter_files = sorted((book / "chapters").glob("*.txt"))
    chapter_files[1].write_bytes(b"\xff\xfe\x00")

    _, selected = load_book_directory(
        book,
        chapter_indexes={1},
        max_chapters=1,
        max_characters=10,
    )

    assert [chapter.index for chapter in selected] == [1]
    with pytest.raises(DataError, match="UTF-8"):
        load_book_directory(book)


def test_book_load_rejects_metadata_count_and_character_limit_early(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("第一章\nshort\n第二章\nanother", encoding="utf-8")
    book = tmp_path / "book"
    import_text(source, book)
    first = sorted((book / "chapters").glob("*.txt"))[0]
    first.write_bytes(b"\xff")

    with pytest.raises(BookSelectionError, match="max-chapters"):
        load_book_directory(book, max_chapters=1)

    first.write_text("sixteen characters", encoding="utf-8")
    with pytest.raises(BookSelectionError, match="max-tts-characters"):
        load_book_directory(book, chapter_indexes={1}, max_characters=5)


def test_generic_source_scrapes_offline_with_robots_and_safe_requests(tmp_path: Path) -> None:
    def handler(url: str) -> FakeResponse:
        if url == "https://example.org/robots.txt":
            return FakeResponse(200, b"User-agent: *\nAllow: /")
        if url == "https://example.org/book?catalog=1":
            return FakeResponse(
                200,
                b'<h1 class="book">Synthetic</h1><p class="author">Tester</p>'
                b'<div class="chapters"><a href="/one?token=remove">One</a></div>',
            )
        if url == "https://example.org/one?token=remove":
            return FakeResponse(
                200,
                b'<h1 class="chapter">One</h1><article class="content">Hello.</article>',
            )
        raise AssertionError(f"unexpected fake URL: {url}")

    sleeps: list[float] = []
    session = FakeSession(handler)
    source = GenericHTMLSource(
        site_config(),
        session=session,  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [PUBLIC_IP],
        sleeper=sleeps.append,
        clock=lambda: 0.0,
    )

    metadata_path = source.scrape_to_dir(tmp_path / "book")
    spec, chapters = load_book_directory(tmp_path / "book")

    assert metadata_path.name == "book.json"
    assert spec.source.url == "https://example.org/book"
    assert spec.chapters[0].source_url == "https://example.org/one"
    assert chapters[0].text == "Hello."
    assert sleeps == [0.5, 0.5]
    for _, kwargs in session.calls:
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert "Authorization" not in kwargs["headers"]
        assert "Cookie" not in kwargs["headers"]


def test_generic_source_obeys_robots_disallow() -> None:
    session = FakeSession(
        lambda url: (
            FakeResponse(200, b"User-agent: *\nDisallow: /book")
            if url.endswith("/robots.txt")
            else pytest.fail("catalog must not be requested")
        )
    )
    source = GenericHTMLSource(
        site_config(),
        session=session,  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [PUBLIC_IP],
        sleeper=lambda seconds: None,
    )

    with pytest.raises(SourceSecurityError, match="robots"):
        source.scrape_to_dir("unused")

    assert [url for url, _ in session.calls] == ["https://example.org/robots.txt"]


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.1.1", "::1", "fc00::1"],
)
def test_generic_source_rejects_private_and_loopback_dns(address: str) -> None:
    session = FakeSession(lambda url: pytest.fail("network must not be reached"))
    source = GenericHTMLSource(
        site_config(),
        session=session,  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [address],
    )

    with pytest.raises(SourceSecurityError, match="non-public"):
        source.scrape_to_dir("unused")

    assert session.calls == []


def test_generic_source_revalidates_external_redirect() -> None:
    def handler(url: str) -> FakeResponse:
        if url.endswith("/robots.txt"):
            return FakeResponse(404)
        return FakeResponse(302, headers={"Location": "https://evil.example/secret"})

    source = GenericHTMLSource(
        site_config(),
        session=FakeSession(handler),  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [PUBLIC_IP],
        sleeper=lambda seconds: None,
    )

    with pytest.raises(SourceSecurityError, match="allowed_domains"):
        source.scrape_to_dir("unused")


def test_generic_source_limits_redirects() -> None:
    def handler(url: str) -> FakeResponse:
        if url.endswith("/robots.txt"):
            return FakeResponse(404)
        marker = int(url.rsplit("=", 1)[1])
        return FakeResponse(302, headers={"Location": f"/book?catalog={marker + 1}"})

    source = GenericHTMLSource(
        site_config(),
        session=FakeSession(handler),  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [PUBLIC_IP],
        sleeper=lambda seconds: None,
    )

    with pytest.raises(SourceSecurityError, match="redirect limit"):
        source.scrape_to_dir("unused")


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(200, headers={"Content-Length": str(MAX_HTML_BYTES + 1)}),
        FakeResponse(200, chunks=[b"x" * MAX_HTML_BYTES, b"x"]),
    ],
)
def test_generic_source_limits_html_response_size(response: FakeResponse) -> None:
    def handler(url: str) -> FakeResponse:
        return FakeResponse(404) if url.endswith("/robots.txt") else response

    source = GenericHTMLSource(
        site_config(),
        session=FakeSession(handler),  # type: ignore[arg-type]
        dns_resolver=lambda hostname: [PUBLIC_IP],
        sleeper=lambda seconds: None,
    )

    with pytest.raises(SourceNetworkError, match="5 MiB"):
        source.scrape_to_dir("unused")


def test_generic_source_rejects_authenticated_requests_session() -> None:
    session = requests.Session()
    session.cookies.set("session", "secret")

    with pytest.raises(SourceSecurityError, match="cookies"):
        GenericHTMLSource(site_config(), session=session)
