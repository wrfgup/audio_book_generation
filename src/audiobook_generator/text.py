from __future__ import annotations

import re
import unicodedata

CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:第[0-9０-９零〇一二三四五六七八九十百千万两]+[章节回卷部篇].*|序章|楔子|后记|尾声)\s*$",
    re.MULTILINE,
)
QUOTE_RE = re.compile(r"[“\"『「]([^”\"』」]+)[”\"』」]")
SPEAKER_HINT_RE = re.compile(
    r"([\u4e00-\u9fff]{1,8}?)(?:低声说|轻声说|嘀咕道|喊道|笑道|叫道|说道|说|问|答|道)"
)
_WINDOWS_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def normalize_text(text: str) -> str:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = [line.strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def chunk_text(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    text = normalize_text(text)
    if len(text) <= max_chars:
        return [text] if text else []

    pieces: list[str] = []
    buffer = ""
    parts = re.split(r"(?<=[。！？；.!?;])", text)
    for part in parts:
        if not part.strip():
            continue
        sub_parts = re.split(r"(?<=[，、,:：])", part) if len(part) > max_chars else [part]
        for sub in sub_parts:
            sub = sub.strip()
            if not sub:
                continue
            if len(buffer) + len(sub) > max_chars and buffer:
                pieces.append(buffer.strip())
                buffer = ""
            if len(sub) > max_chars:
                start = 0
                while start < len(sub):
                    pieces.append(sub[start : start + max_chars].strip())
                    start += max_chars
                continue
            buffer += sub
    if buffer.strip():
        pieces.append(buffer.strip())
    return pieces


def split_chapters(text: str, *, fallback_title: str) -> list[tuple[str, str]]:
    """Split normalized text on Chinese chapter headings.

    Text before the first heading is retained as a preface instead of being
    silently discarded. Empty headed chapters are rejected by the importer,
    which can provide a more useful input error at that boundary.
    """

    normalized = normalize_text(text)
    if not normalized:
        return []
    matches = list(CHAPTER_HEADING_RE.finditer(normalized))
    if not matches:
        return [(fallback_title.strip() or "未命名章节", normalized)]

    chapters: list[tuple[str, str]] = []
    preface = normalized[: matches[0].start()].strip()
    if preface:
        chapters.append(("序章", preface))
    for position, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[position + 1].start() if position + 1 < len(matches) else len(normalized)
        title = match.group(0).strip()
        body = normalized[body_start:body_end].strip()
        chapters.append((title, body))
    return chapters


def safe_filename_component(
    value: str, *, fallback: str = "untitled", max_length: int = 120
) -> str:
    """Return a cross-platform filename component safe on Windows as well."""

    if max_length <= 0:
        raise ValueError("max_length must be greater than zero")
    normalized = unicodedata.normalize("NFC", value)
    normalized = _WINDOWS_INVALID_RE.sub("-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip(" .-")
    if not normalized or normalized in {".", ".."}:
        normalized = fallback
    if normalized.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    normalized = normalized[:max_length].rstrip(" .")
    return normalized or fallback[:max_length]


def split_narration_and_dialogue(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_line in normalize_text(text).splitlines():
        if not raw_line.strip():
            continue
        cursor = 0
        matches = list(QUOTE_RE.finditer(raw_line))
        if not matches:
            items.append(("narration", raw_line))
            continue

        for match in matches:
            if match.start() > cursor:
                prefix = raw_line[cursor : match.start()].strip(" ，。；：:、")
                if prefix:
                    items.append(("narration", prefix))
            quoted = match.group(1).strip()
            if quoted:
                items.append(("dialogue", quoted))
            cursor = match.end()

        suffix = raw_line[cursor:].strip(" ，。；：:、")
        if suffix:
            items.append(("narration", suffix))
    return items


def infer_speaker(context: str) -> str | None:
    match = SPEAKER_HINT_RE.search(context)
    return match.group(1) if match else None


def clean_chapter_content(text: str) -> str:
    text = normalize_text(text)
    cleaned_lines: list[str] = []
    junk_patterns = (
        "上一章",
        "下一章",
        "返回目录",
        "加入书签",
        "推荐本书",
        "手机阅读",
        "投推荐票",
        "章节报错",
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern in stripped for pattern in junk_patterns):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines)
