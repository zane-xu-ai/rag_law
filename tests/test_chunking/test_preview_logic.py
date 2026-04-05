"""chunking.webui.preview_logic 纯函数。"""

from chunking.webui.preview_logic import (
    adjacent_overlaps,
    overlap_between_adjacent,
    pick_display_indices,
    section_for_display_index,
    source_paragraph_count,
)


def test_overlap_between_adjacent() -> None:
    assert overlap_between_adjacent(10, 7) == 3
    assert overlap_between_adjacent(7, 10) == 0


def test_adjacent_overlaps_three_chunks() -> None:
    # 与滑窗一致时，相邻重叠应等于 chunk_size - step = overlap（除末块外）
    ranges = [(0, 4), (3, 7), (6, 10)]
    assert adjacent_overlaps(ranges) == [1, 1]


def test_source_paragraph_count() -> None:
    assert source_paragraph_count("") == 0
    assert source_paragraph_count("a\n\nb") == 2
    assert source_paragraph_count("only") == 1


def test_pick_display_indices() -> None:
    assert pick_display_indices(0) == []
    assert pick_display_indices(3) == [0, 1, 2]
    assert len(pick_display_indices(16)) == 15
    assert pick_display_indices(16)[:5] == [0, 1, 2, 3, 4]
    assert pick_display_indices(16)[-5:] == [11, 12, 13, 14, 15]


def test_section_for_display_index() -> None:
    assert section_for_display_index(0, 10) == "all"
    assert section_for_display_index(0, 20) == "first"
    assert section_for_display_index(19, 20) == "last"
