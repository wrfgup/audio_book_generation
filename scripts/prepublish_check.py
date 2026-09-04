#!/usr/bin/env python3
"""Fail a release when its Git candidate set contains likely private material.

The candidate set is the union of tracked files and untracked, non-ignored files.
This deliberately works before the repository has its first commit. Ignored local
material is never opened or inspected.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_FIXTURE_BYTES = 256 * 1024
MAX_PROSE_BYTES = 64 * 1024

MEDIA_SUFFIXES = {
    ".aac",
    ".aif",
    ".aiff",
    ".avi",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}
RAW_HTML_SUFFIXES = {".htm", ".html"}
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".css",
    ".env",
    ".htm",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

BLOCKED_TOP_LEVEL = {
    "audio",
    "books",
    "cache",
    "chapters",
    "downloads",
    "input",
    "inputs",
    "media",
    "output",
    "outputs",
    "raw",
    "raw_html",
    "runs",
}
BLOCKED_ROOT_FILES = {
    "config.json",
    "speaker_dict.json",
    "tone_blacklist.json",
}
LEGACY_PATHS = {
    "backup.py",
    "chapter2audio.py",
    "conf.py",
    "ebook2audio.py",
    "snake",
    "split_chapter.py",
    "src/audiobook_generator/source_23qb.py",
}

PLACEHOLDER_WORDS = {
    "changeme",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "redacted",
    "replace",
    "sample",
    "test",
    "unset",
    "your_",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    ),
    (
        "openai-api-key",
        re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "github-token",
        re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    ),
    (
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "slack-token",
        re.compile(r"\bxox(?:b|p|a|r|s)-[A-Za-z0-9-]{20,}\b"),
    ),
    (
        "credential-in-url",
        re.compile(r"https?://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE),
    ),
    (
        "secret-assignment",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
            r"\b\s*[:=]\s*[\"']?(?P<value>[^\s\"',;#]{8,})",
            re.IGNORECASE,
        ),
    ),
)

IPV4_PATTERN = re.compile(r"(?<![\w.])(?P<ip>(?:\d{1,3}\.){3}\d{1,3})(?![\w.])")
IPV6_PATTERN = re.compile(r"(?<![\w:])(?P<ip>(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4})(?![\w:])")
BRACKETED_IPV6_PATTERN = re.compile(r"\[(?P<ip>[0-9A-Fa-f:]{2,})\]")
WINDOWS_USER_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]+(?:Users|Documents and Settings)"
    r"[\\/]+[^\\/\s:\"']+)",
    re.IGNORECASE,
)
POSIX_USER_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9._-]+(?:/[^\s\"']*)?"
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"{location} [{self.rule}]"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan tracked and unignored files for material unsafe to publish."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--max-file-size-mib",
        type=float,
        default=DEFAULT_MAX_BYTES / (1024 * 1024),
        help="maximum candidate file size in MiB (default: 5)",
    )
    return parser.parse_args(argv)


def git_candidates(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise RuntimeError("git is required to identify the public candidate set") from exc

    if result.returncode != 0:
        raise RuntimeError("unable to enumerate Git candidate files")

    names = {os.fsdecode(item) for item in result.stdout.split(b"\0") if item}
    return [root / PurePosixPath(name) for name in sorted(names)]


def relative_name(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_test_fixture(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return len(parts) >= 2 and parts[:2] == ("tests", "fixtures")


def is_test_code(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool(path.parts and path.parts[0] == "tests" and path.suffix in {".py", ".pyi"})


def is_public_fixture(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return is_test_fixture(relative) or bool(parts and parts[0] == "examples")


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def looks_like_placeholder(value: str) -> bool:
    lowered = value.casefold()
    variable_reference = re.fullmatch(
        r"(?:config|env|os|self|settings)(?:\.[A-Za-z_][A-Za-z0-9_]*)+", value
    )
    return (
        any(word in lowered for word in PLACEHOLDER_WORDS)
        or set(lowered) <= {"x", ".", "-"}
        or variable_reference is not None
        or value.startswith(("${", "{{"))
    )


def content_findings(relative: str, text: str) -> list[Finding]:
    if is_test_fixture(relative):
        return []

    findings: list[Finding] = []
    test_code = is_test_code(relative)
    for rule, pattern in SECRET_PATTERNS:
        if test_code and rule in {"credential-in-url", "secret-assignment"}:
            continue
        for match in pattern.finditer(text):
            value = match.groupdict().get("value", "")
            if value and looks_like_placeholder(value):
                continue
            findings.append(Finding(relative, rule, line_number(text, match.start())))

    if not test_code:
        for pattern in (IPV4_PATTERN, IPV6_PATTERN, BRACKETED_IPV6_PATTERN):
            for match in pattern.finditer(text):
                try:
                    ipaddress.ip_address(match.group("ip"))
                except ValueError:
                    continue
                findings.append(
                    Finding(relative, "bare-ip-address", line_number(text, match.start()))
                )

        for pattern in (WINDOWS_USER_PATH_PATTERN, POSIX_USER_PATH_PATTERN):
            for match in pattern.finditer(text):
                findings.append(
                    Finding(relative, "user-absolute-path", line_number(text, match.start()))
                )

    return findings


def path_findings(relative: str, size: int, max_bytes: int) -> list[Finding]:
    findings: list[Finding] = []
    path = PurePosixPath(relative)
    lowered = relative.casefold()
    parts = tuple(part.casefold() for part in path.parts)
    suffix = path.suffix.casefold()
    public_fixture = is_public_fixture(relative)

    if parts and parts[0] in BLOCKED_TOP_LEVEL:
        findings.append(Finding(relative, "private-runtime-path"))
    if len(parts) == 1 and parts[0] in BLOCKED_ROOT_FILES:
        findings.append(Finding(relative, "private-root-config"))
    if lowered in LEGACY_PATHS or any(lowered.startswith(f"{item}/") for item in LEGACY_PATHS):
        findings.append(Finding(relative, "legacy-private-code"))
    if size > max_bytes:
        findings.append(Finding(relative, "file-too-large"))
    if public_fixture and size > MAX_FIXTURE_BYTES:
        findings.append(Finding(relative, "fixture-too-large"))
    if suffix in MEDIA_SUFFIXES and not public_fixture:
        findings.append(Finding(relative, "generated-media"))
    if suffix in RAW_HTML_SUFFIXES and not public_fixture:
        findings.append(Finding(relative, "raw-html"))
    if suffix == ".txt" and size > MAX_PROSE_BYTES and not public_fixture:
        findings.append(Finding(relative, "possible-copyrighted-prose"))
    return findings


def scan_file(root: Path, candidate: Path, max_bytes: int) -> list[Finding]:
    relative = relative_name(root, candidate)
    findings: list[Finding] = []

    if candidate.is_symlink():
        return [Finding(relative, "symbolic-link")]
    if not candidate.exists() or not candidate.is_file():
        return [Finding(relative, "missing-candidate")]

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return [Finding(relative, "path-outside-repository")]

    try:
        size = candidate.stat().st_size
    except OSError:
        return [Finding(relative, "unreadable-file")]
    findings.extend(path_findings(relative, size, max_bytes))

    if size > max_bytes:
        return findings

    try:
        data = candidate.read_bytes()
    except OSError:
        findings.append(Finding(relative, "unreadable-file"))
        return findings

    suffix = candidate.suffix.casefold()
    likely_text = suffix in TEXT_SUFFIXES or candidate.name.startswith(".env")
    if b"\0" in data and not likely_text:
        return findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if likely_text:
            findings.append(Finding(relative, "non-utf8-text"))
        return findings

    findings.extend(content_findings(relative, text))
    return findings


def run(root: Path, max_bytes: int) -> tuple[int, list[Finding]]:
    candidates = git_candidates(root)
    findings: set[Finding] = set()
    for candidate in candidates:
        findings.update(scan_file(root, candidate, max_bytes))
    return len(candidates), sorted(findings)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    max_bytes = int(args.max_file_size_mib * 1024 * 1024)
    if max_bytes <= 0:
        print("error: --max-file-size-mib must be greater than zero", file=sys.stderr)
        return 2

    try:
        candidate_count, findings = run(root, max_bytes)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if findings:
        print(f"Prepublish check failed with {len(findings)} finding(s):", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.render()}", file=sys.stderr)
        return 1

    print(f"Prepublish check passed ({candidate_count} candidate files scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
