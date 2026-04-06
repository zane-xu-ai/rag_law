"""ingest.dump_format：重叠 ** 与块间空行。"""

from __future__ import annotations

from ingest.dump_format import annotate_chunk_line, build_file_body, overlap_local


def test_overlap_local_adjacent_sliding() -> None:
    # 块0 [0,10) 块1 [5,15) 重叠 [5,10)
    assert overlap_local(0, 10, 5, 15) == (5, 10)
    assert overlap_local(5, 15, 0, 10) == (0, 5)


def test_annotate_two_chunks_overlap() -> None:
    """两块重叠：前块末尾与后块开头为同一原文区间。"""
    a = {"text": "0123456789", "char_start": 0, "char_end": 10}
    b = {"text": "56789abcde", "char_start": 5, "char_end": 15}
    line_a = annotate_chunk_line(a["text"], 0, 10, None, b)
    line_b = annotate_chunk_line(b["text"], 5, 15, a, None)
    assert "56789" in line_a
    assert "56789" in line_b
    assert "【56789】" in line_a
    assert "【56789】" in line_b


def test_build_file_body_blank_between_chunks() -> None:
    out = build_file_body(
        [
            {"text": "aa", "char_start": 0, "char_end": 2},
            {"text": "bb", "char_start": 2, "char_end": 4},
        ]
    )
    assert out == "aa\n\nbb\n"
