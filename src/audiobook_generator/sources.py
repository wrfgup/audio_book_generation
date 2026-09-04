"""Local text import and a constrained, site-configured HTML source."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections.abc import Callable, Iterable, Set
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .io_utils import (
    DataError,
    atomic_write_json,
    atomic_write_text,
    read_json_object,
    validate_document,
)
from .models import (
    MAX_CHAPTER_BYTES,
    BookChapterSpec,
    BookInfo,
    BookSourceSpec,
    BookSpec,
    Chapter,
    SiteConfig,
)
from .text import normalize_text, safe_filename_component, split_chapters

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_TEXT_INPUT_BYTES = 512 * 1024 * 1024
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


class SourceError(RuntimeError):
    """Base class for safe-to-display source failures."""


class SourceSecurityError(SourceError, ValueError):
    """A URL or redirect violated the source security policy."""


class SourceNetworkError(SourceError):
    """A bounded source request could not be completed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BookSelectionError(DataError):
    """A requested chapter selection or pre-read build limit is invalid."""


DNSResult = str | tuple[Any, ...]
DNSResolver = Callable[[str], Iterable[DNSResult]]


def load_book_directory(
    path: str | Path,
    *,
    chapter_indexes: Set[int] | None = None,
    max_chapters: int | None = None,
    max_characters: int | None = None,
) -> tuple[BookSpec, list[Chapter]]:
    """Load and fully validate a standard book directory.

    This performs both schema validation and filesystem containment checks.
    Validation occurs before any chapter text is returned to a caller.
    """

    root = Path(path)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise DataError("book directory does not exist") from exc
    if not resolved_root.is_dir():
        raise DataError("book input is not a directory")

    metadata_path = _resolve_existing_within(resolved_root, resolved_root / "book.json")
    spec = validate_document(BookSpec, read_json_object(metadata_path))

    chapter_root = _resolve_existing_within(resolved_root, resolved_root / "chapters")
    if not chapter_root.is_dir():
        raise DataError("chapters is not a directory")

    selected_items = spec.chapters
    if chapter_indexes is not None:
        available = {item.index for item in spec.chapters}
        missing = sorted(set(chapter_indexes) - available)
        if missing:
            rendered = ", ".join(str(index) for index in missing[:10])
            raise BookSelectionError(f"Requested chapter indexes do not exist: {rendered}")
        selected_items = [item for item in spec.chapters if item.index in chapter_indexes]
    if max_chapters is not None:
        if max_chapters <= 0:
            raise BookSelectionError("max chapters must be greater than zero")
        if len(selected_items) > max_chapters:
            raise BookSelectionError(
                f"Selected {len(selected_items)} chapters, exceeding --max-chapters={max_chapters}."
            )
    if max_characters is not None and max_characters <= 0:
        raise BookSelectionError("max TTS characters must be greater than zero")

    chapters: list[Chapter] = []
    character_count = 0
    for item in selected_items:
        candidate = resolved_root / Path(*item.file.split("/"))
        chapter_path = _resolve_existing_within(chapter_root, candidate)
        if not chapter_path.is_file():
            raise DataError("chapter input is not a regular file")
        try:
            if chapter_path.stat().st_size > MAX_CHAPTER_BYTES:
                raise DataError("chapter exceeds the 5 MiB size limit")
            raw = chapter_path.read_text(encoding="utf-8-sig")
        except DataError:
            raise
        except (OSError, UnicodeError) as exc:
            raise DataError("chapter input could not be read as UTF-8") from exc
        text = normalize_text(raw)
        if not text:
            raise DataError("chapter text must not be empty")
        character_count += len(text)
        if max_characters is not None and character_count > max_characters:
            raise BookSelectionError(
                "Selected text exceeds --max-tts-characters "
                f"({character_count} > {max_characters})."
            )
        chapters.append(
            Chapter(
                index=item.index,
                title=item.title,
                source_url=item.source_url,
                text=text,
            )
        )
    return spec, chapters


def import_text(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    title: str | None = None,
    author: str | None = None,
    encoding: str = "utf-8-sig",
) -> Path:
    """Import one text file or a directory of ``.txt`` files."""

    source = Path(input_path)
    try:
        if source.is_file():
            inputs = [source]
            default_book_title = source.stem
        elif source.is_dir():
            inputs = sorted(
                (
                    entry
                    for entry in source.iterdir()
                    if entry.is_file() and entry.suffix.lower() == ".txt"
                ),
                key=lambda entry: _natural_key(entry.name),
            )
            default_book_title = source.name
        else:
            raise DataError("text input must be a file or directory")
    except OSError as exc:
        raise DataError("text input could not be inspected") from exc
    if not inputs:
        raise DataError("text directory contains no .txt files")

    imported: list[tuple[str, str]] = []
    for text_path in inputs:
        try:
            if text_path.stat().st_size > MAX_TEXT_INPUT_BYTES:
                raise DataError("text input exceeds the import size limit")
            raw = text_path.read_text(encoding=encoding)
        except DataError:
            raise
        except (LookupError, OSError, UnicodeError) as exc:
            raise DataError("text input could not be read with the selected encoding") from exc
        imported.extend(split_chapters(raw, fallback_title=text_path.stem))

    if not imported:
        raise DataError("text input is empty")
    for _, chapter_text in imported:
        if not chapter_text:
            raise DataError("chapter text must not be empty")
        if len(chapter_text.encode("utf-8")) > MAX_CHAPTER_BYTES:
            raise DataError("chapter exceeds the 5 MiB size limit")

    book_title = (title or default_book_title).strip()
    if not book_title:
        raise DataError("book title must not be empty")
    clean_author = author.strip() if author and author.strip() else None

    root, chapter_dir = _prepare_output_directory(output_dir)
    chapter_specs: list[BookChapterSpec] = []
    for index, (chapter_title, chapter_text) in enumerate(imported, start=1):
        safe_title = safe_filename_component(
            chapter_title,
            fallback=f"chapter-{index:04d}",
        )
        filename = f"{index:04d}-{safe_title}.txt"
        atomic_write_text(chapter_dir / filename, chapter_text.rstrip() + "\n")
        chapter_specs.append(
            BookChapterSpec(
                index=index,
                title=chapter_title,
                file=f"chapters/{filename}",
                source_url=None,
            )
        )

    spec = BookSpec(
        schema_version=1,
        source=BookSourceSpec(type="local_text"),
        book=BookInfo(title=book_title, author=clean_author),
        chapters=chapter_specs,
    )
    metadata_path = atomic_write_json(root / "book.json", spec)
    load_book_directory(root)
    return metadata_path


def load_site_config(path: str | Path) -> SiteConfig:
    config = validate_document(SiteConfig, read_json_object(path))
    _validate_site_config_security(config)
    return config


class GenericHTMLSource:
    """Scrape one explicitly configured, authorized, public HTML catalog."""

    def __init__(
        self,
        config: SiteConfig,
        *,
        session: requests.Session | None = None,
        dns_resolver: DNSResolver | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout: tuple[float, float] = (5.0, 30.0),
    ) -> None:
        _validate_site_config_security(config)
        self.config = config
        self.session = session or requests.Session()
        _reject_authenticated_session(self.session)
        self._resolve_dns = dns_resolver or _default_dns_resolver
        self._sleep = sleeper
        self._clock = clock
        self._timeout = timeout
        self._last_request_at: float | None = None
        self._robots: dict[str, RobotFileParser | None] = {}

    def scrape_to_dir(self, output_dir: str | Path) -> Path:
        catalog_html, catalog_url = self._get_bytes(self.config.start_url)
        catalog = BeautifulSoup(catalog_html, "html.parser")
        title = self._select_text(catalog, self.config.selectors.book_title, required=True)
        if title is None:  # pragma: no cover - required=True raises first
            raise SourceError("required HTML metadata is missing")
        author = (
            self._select_text(catalog, self.config.selectors.author, required=False)
            if self.config.selectors.author
            else None
        )
        links = self._chapter_links(catalog, catalog_url)
        if self.config.max_chapters is not None:
            links = links[: self.config.max_chapters]
        if not links:
            raise SourceError("catalog contains no chapter links")

        chapters: list[Chapter] = []
        for index, (link_title, chapter_url) in enumerate(links, start=1):
            chapter_html, final_url = self._get_bytes(chapter_url)
            chapter_page = BeautifulSoup(chapter_html, "html.parser")
            if self.config.selectors.chapter_title:
                chapter_title = self._select_text(
                    chapter_page,
                    self.config.selectors.chapter_title,
                    required=False,
                )
            else:
                chapter_title = None
            content = self._select_content(chapter_page, self.config.selectors.chapter_content)
            if len(content.encode("utf-8")) > MAX_CHAPTER_BYTES:
                raise SourceError("extracted chapter exceeds the 5 MiB size limit")
            chapters.append(
                Chapter(
                    index=index,
                    title=chapter_title or link_title or f"Chapter {index}",
                    source_url=_url_without_query(final_url),
                    text=content,
                )
            )

        return _write_web_book(
            output_dir,
            title=title,
            author=author,
            source_url=_url_without_query(catalog_url),
            chapters=chapters,
        )

    def _get_bytes(self, url: str, *, check_robots: bool = True) -> tuple[bytes, str]:
        current = url
        visited: set[str] = set()
        for redirect_count in range(MAX_REDIRECTS + 1):
            self._validate_request_url(current)
            if check_robots and not self._robots_allows(current):
                raise SourceSecurityError("robots.txt disallows this source URL")
            if current in visited:
                raise SourceSecurityError("source redirect loop detected")
            visited.add(current)
            response = self._request_once(current)
            try:
                status = int(response.status_code)
                if status in _REDIRECT_STATUSES:
                    if redirect_count >= MAX_REDIRECTS:
                        raise SourceSecurityError("source exceeded the redirect limit")
                    location = response.headers.get("Location")
                    if not location:
                        raise SourceNetworkError("source redirect is missing a destination")
                    current = urldefrag(urljoin(current, location))[0]
                    continue
                if not 200 <= status < 300:
                    raise SourceNetworkError(
                        "source returned an unsuccessful HTTP status",
                        status_code=status,
                    )
                return self._read_bounded_response(response), current
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        raise SourceSecurityError("source exceeded the redirect limit")

    def _request_once(self, url: str) -> Any:
        self._respect_interval()
        try:
            response = self.session.get(
                url,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": "text/html, text/plain;q=0.9",
                },
                timeout=self._timeout,
                stream=True,
                allow_redirects=False,
            )
        except (requests.RequestException, OSError) as exc:
            raise SourceNetworkError("source request failed") from exc
        self._last_request_at = self._clock()
        return response

    def _read_bounded_response(self, response: Any) -> bytes:
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_HTML_BYTES:
                    raise SourceNetworkError("source response exceeds the 5 MiB limit")
            except ValueError as exc:
                raise SourceNetworkError("source returned an invalid Content-Length") from exc

        body = bytearray()
        iterator = getattr(response, "iter_content", None)
        chunks = iterator(chunk_size=64 * 1024) if callable(iterator) else [response.content]
        for chunk in chunks:
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            body.extend(chunk)
            if len(body) > MAX_HTML_BYTES:
                raise SourceNetworkError("source response exceeds the 5 MiB limit")
        return bytes(body)

    def _robots_allows(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            try:
                body, final_url = self._get_bytes(robots_url, check_robots=False)
            except SourceNetworkError as exc:
                # A missing robots file means no published restrictions. Other
                # errors fail closed because they may be transient policy data.
                response_status = getattr(exc, "status_code", None)
                if response_status == 404:
                    self._robots[origin] = None
                    return True
                raise
            parser = RobotFileParser()
            parser.set_url(final_url)
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            self._robots[origin] = parser
        cached_parser = self._robots[origin]
        return cached_parser is None or cached_parser.can_fetch(self.config.user_agent, url)

    def _validate_request_url(self, url: str) -> None:
        parsed = _validate_https_url(url, self.config.allowed_domains)
        try:
            resolved = self._resolve_dns(parsed.hostname or "")
        except OSError as exc:
            raise SourceNetworkError("source hostname could not be resolved") from exc
        addresses = _extract_addresses(resolved)
        if not addresses:
            raise SourceNetworkError("source hostname resolved to no addresses")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise SourceSecurityError("source DNS returned an invalid address") from exc
            if not _is_public_address(ip):
                raise SourceSecurityError("source hostname resolves to a non-public address")

    def _respect_interval(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.config.request_interval_seconds - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)

    def _chapter_links(self, page: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
        try:
            elements = page.select(self.config.selectors.chapter_links)
        except Exception as exc:
            raise SourceError("chapter link CSS selector is invalid") from exc
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for element in elements:
            href = element.get("href")
            if not isinstance(href, str) or not href.strip():
                continue
            absolute = urldefrag(urljoin(base_url, href))[0]
            _validate_https_url(absolute, self.config.allowed_domains)
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append((normalize_text(element.get_text(" ", strip=True)), absolute))
        return links

    @staticmethod
    def _select_text(page: BeautifulSoup, selector: str, *, required: bool) -> str | None:
        try:
            element = page.select_one(selector)
        except Exception as exc:
            raise SourceError("CSS selector is invalid") from exc
        value = normalize_text(element.get_text(" ", strip=True)) if element else ""
        if required and not value:
            raise SourceError("required HTML metadata is missing")
        return value or None

    @staticmethod
    def _select_content(page: BeautifulSoup, selector: str) -> str:
        try:
            elements = page.select(selector)
        except Exception as exc:
            raise SourceError("chapter content CSS selector is invalid") from exc
        text = normalize_text("\n".join(element.get_text("\n", strip=True) for element in elements))
        if not text:
            raise SourceError("chapter content is empty")
        return text


def _write_web_book(
    output_dir: str | Path,
    *,
    title: str,
    author: str | None,
    source_url: str,
    chapters: list[Chapter],
) -> Path:
    root, chapter_dir = _prepare_output_directory(output_dir)
    chapter_specs: list[BookChapterSpec] = []
    for chapter in chapters:
        filename = chapter.filename()
        atomic_write_text(chapter_dir / filename, chapter.text.rstrip() + "\n")
        chapter_specs.append(
            BookChapterSpec(
                index=chapter.index,
                title=chapter.title,
                file=f"chapters/{filename}",
                source_url=chapter.source_url,
            )
        )
    spec = BookSpec(
        schema_version=1,
        source=BookSourceSpec(type="web", url=source_url),
        book=BookInfo(title=title, author=author),
        chapters=chapter_specs,
    )
    metadata_path = atomic_write_json(root / "book.json", spec)
    load_book_directory(root)
    return metadata_path


def _prepare_output_directory(output_dir: str | Path) -> tuple[Path, Path]:
    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise DataError("output is not a directory")
        chapter_dir = resolved_root / "chapters"
        chapter_dir.mkdir(exist_ok=True)
        resolved_chapters = chapter_dir.resolve(strict=True)
    except DataError:
        raise
    except OSError as exc:
        raise DataError("output directory could not be prepared") from exc
    if not resolved_chapters.is_dir() or not _is_relative_to(resolved_chapters, resolved_root):
        raise DataError("chapters output escapes the book directory")
    return resolved_root, resolved_chapters


def _resolve_existing_within(root: Path, candidate: Path) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DataError("required book input is missing") from exc
    if not _is_relative_to(resolved, root):
        raise DataError("book path escapes its allowed directory")
    return resolved


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)
    )


def _validate_site_config_security(config: SiteConfig) -> None:
    for domain in config.allowed_domains:
        _validate_allowed_domain(domain)
    _validate_https_url(config.start_url, config.allowed_domains)


def _validate_allowed_domain(domain: str) -> None:
    if not domain or any(character in domain for character in "/:@?#[]"):
        raise SourceSecurityError("allowed domain is invalid")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").rstrip(".").lower()
    except UnicodeError as exc:
        raise SourceSecurityError("allowed domain is invalid") from exc
    try:
        ipaddress.ip_address(ascii_domain)
    except ValueError:
        pass
    else:
        raise SourceSecurityError("allowed_domains must contain domain names, not IP addresses")
    if ascii_domain == "localhost" or ascii_domain.endswith(".localhost"):
        raise SourceSecurityError("loopback domains are not allowed")
    labels = ascii_domain.split(".")
    if (
        len(ascii_domain) > 253
        or len(labels) < 2
        or any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels)
    ):
        raise SourceSecurityError("allowed domain is invalid")


def _validate_https_url(url: str, allowed_domains: list[str]) -> Any:
    if any(ord(character) <= 0x20 for character in url) or "\\" in url:
        raise SourceSecurityError("source URL contains invalid characters")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceSecurityError("source URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise SourceSecurityError("source URL must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise SourceSecurityError("source URL contains an invalid port") from exc
    hostname = parsed.hostname.encode("idna").decode("ascii").rstrip(".").lower()
    normalized_allowed = [
        domain.encode("idna").decode("ascii").rstrip(".").lower() for domain in allowed_domains
    ]
    if hostname not in normalized_allowed:
        raise SourceSecurityError("source hostname is outside allowed_domains")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise SourceSecurityError("source URL must use a domain name")
    return parsed


def _default_dns_resolver(hostname: str) -> Iterable[DNSResult]:
    return socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)


def _reject_authenticated_session(session: object) -> None:
    """Prevent accidental cookie, netrc, or session-authenticated scraping."""

    if not isinstance(session, requests.Session):
        return
    if session.auth:
        raise SourceSecurityError("authenticated source sessions are not supported")
    forbidden_headers = {"authorization", "cookie", "proxy-authorization"}
    if any(name.lower() in forbidden_headers for name in session.headers):
        raise SourceSecurityError("authenticated source headers are not supported")
    if session.cookies:
        raise SourceSecurityError("source cookies are not supported")
    session.trust_env = False


def _extract_addresses(results: Iterable[DNSResult]) -> list[str]:
    addresses: list[str] = []
    for result in results:
        if isinstance(result, str):
            addresses.append(result)
        elif isinstance(result, tuple) and len(result) >= 5:
            socket_address = result[4]
            if isinstance(socket_address, tuple) and socket_address:
                addresses.append(str(socket_address[0]))
    return list(dict.fromkeys(addresses))


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
