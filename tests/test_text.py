from __future__ import annotations

import pytest

from audiobook_generator.text import (
    chunk_text,
    infer_speaker,
    normalize_text,
    safe_filename_component,
    split_chapters,
    split_narration_and_dialogue,
)


def test_normalize_text_handles_bom_newlines_spaces_and_blank_runs() -> None:
    raw = "\ufeff  第一段\xa0\r\n\r\n\r\n　第二段  \r"

    assert normalize_text(raw) == "第一段\n\n第二段"


def test_split_chapters_recognizes_chinese_headings_and_keeps_preface() -> None:
    chapters = split_chapters(
        "简介\n第一章 出发\n甲。\n第十二回 相遇\n乙。",
        fallback_title="fallback",
    )

    assert chapters == [
        ("序章", "简介"),
        ("第一章 出发", "甲。"),
        ("第十二回 相遇", "乙。"),
    ]


def test_split_chapters_without_heading_is_one_chapter() -> None:
    assert split_chapters("只有正文。", fallback_title="文件名") == [("文件名", "只有正文。")]


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_chunk_text_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        chunk_text("正文", limit)


def test_chunk_text_never_exceeds_limit() -> None:
    chunks = chunk_text("第一句很短。第二句稍微长一点，而且还有逗号。最后一句。", 8)

    assert "".join(chunks) == "第一句很短。第二句稍微长一点，而且还有逗号。最后一句。"
    assert all(0 < len(chunk) <= 8 for chunk in chunks)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ('a<b>:c"d/e\\f|g?h*', "a-b-c-d-e-f-g-h"),
        ("CON", "_CON"),
        ("lpt1.txt", "_lpt1.txt"),
        ("trailing. ", "trailing"),
        ("", "chapter"),
    ],
)
def test_safe_filename_component_is_windows_safe(name: str, expected: str) -> None:
    assert safe_filename_component(name, fallback="chapter") == expected


def test_safe_filename_component_respects_length() -> None:
    assert safe_filename_component("字" * 200, max_length=30) == "字" * 30


def test_dialogue_detection_and_rule_based_speaker() -> None:
    items = split_narration_and_dialogue("小明说道：“你好。”\n\n随后他离开了。")

    assert items == [
        ("narration", "小明说道"),
        ("dialogue", "你好。"),
        ("narration", "随后他离开了。"),
    ]
    assert infer_speaker("小明说道") == "小明"
