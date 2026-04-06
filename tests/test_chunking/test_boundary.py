"""句边界对齐：chunking.boundary 与 boundary_aware 路径。"""

from __future__ import annotations

from pathlib import Path

import pytest

from chunking.boundary import (
    BOUNDARY_CHARS,
    _clamp_start_for_overlap,
    _clamp_start_to_overlap_range,
    adjust_end,
    adjust_start,
    iter_text_slices_boundary_aware,
)
from chunking.split import iter_chunks_for_text, iter_text_slices


def test_boundary_chars_includes_punct_and_newline() -> None:
    assert "。" in BOUNDARY_CHARS
    assert "\n" in BOUNDARY_CHARS
    assert "；" in BOUNDARY_CHARS


def test_adjust_start_no_boundary_returns_s0() -> None:
    t = "a" * 50
    s0 = 20
    assert adjust_start(t, s0, max_probe=30) == s0


def test_adjust_start_prefers_smaller_delta_tie_backward() -> None:
    # 索引：0-8 为 x，9 与 11 为「；」，s0=11 时向后得 s=10（|Δ|=1）、向前得 s=12（|Δ|=1），平局优先向后
    t = "x" * 9 + "；" + "x" + "；" + "x" * 20
    assert adjust_start(t, 11, max_probe=30) == 10


def test_adjust_start_only_forward() -> None:
    t = "abcdefghij"
    # s0=5 前无标点，向前在 7 有「。」（需构造）
    t2 = "abcde。fghi"
    assert adjust_start(t2, 5, max_probe=30) == 6  # 。之后


def test_adjust_end_at_eof() -> None:
    t = "abc"
    assert adjust_end(t, 3, max_probe=30) == 3


def test_iter_text_slices_boundary_aware_aligns_to_period() -> None:
    # 纯滑窗可能在「句中」开窗口；句界模式应把块首/尾向标点靠拢（在 30 字内）
    parts = list(
        iter_text_slices_boundary_aware(
            "第一节内容很长" + "。" + "第二节开始",
            chunk_size=8,
            chunk_overlap=0,
            max_probe=30,
        )
    )
    assert len(parts) >= 1
    texts = [p[0] for p in parts]
    assert any("。" in x for x in texts)


def test_iter_chunks_boundary_aware_flag() -> None:
    plain = list(
        iter_chunks_for_text(
            "a" * 40,
            source_file="x.md",
            source_path=None,
            chunk_size=20,
            chunk_overlap=0,
            boundary_aware=False,
        )
    )
    aware = list(
        iter_chunks_for_text(
            "a" * 40,
            source_file="x.md",
            source_path=None,
            chunk_size=20,
            chunk_overlap=0,
            boundary_aware=True,
            overlap_floor=0,
        )
    )
    assert len(plain) == 2
    assert len(aware) == 2
    assert plain[0].text == aware[0].text


def test_boundary_aware_newline_chunk() -> None:
    text = "第一行\n第二行"
    chunks = list(
        iter_text_slices_boundary_aware(text, chunk_size=4, chunk_overlap=0, max_probe=30)
    )
    assert chunks


def test_iter_text_slices_same_as_plain_when_no_boundary_effect() -> None:
    """无标点时边界对齐应退回初值，块序列与纯滑窗一致。"""
    t = "a" * 25
    raw = list(iter_text_slices(t, chunk_size=10, chunk_overlap=0))
    adj = list(iter_text_slices_boundary_aware(t, chunk_size=10, chunk_overlap=0))
    assert [x[1:] for x in raw] == [x[1:] for x in adj]


def test_clamp_start_overlap_uses_upper_bound_not_lower() -> None:
    """重叠至少 L 字 ⟺ start <= prev_end - L；不得用 max 把句界对齐结果右推。"""
    assert _clamp_start_for_overlap(1380, 1506, 100) == 1380
    assert _clamp_start_for_overlap(1450, 1506, 100) == 1406
    assert _clamp_start_for_overlap(100, None, 100) == 100


def test_clamp_start_to_overlap_range_pins_interval() -> None:
    """重叠在 [floor, ceiling] 即 start 在 [prev_end-ceiling, prev_end-floor]。"""
    assert _clamp_start_to_overlap_range(18225, 18286, 40, 160) == 18225
    assert _clamp_start_to_overlap_range(18100, 18286, 40, 160) == 18126
    assert _clamp_start_to_overlap_range(18300, 18286, 40, 160) == 18246


def test_adjust_start_weak_uses_comma_when_no_strong_in_window() -> None:
    """±30 内无强句界时可用弱标点（逗号）。"""
    t = "x" * 20 + "，" + "y" * 50
    s0 = 22
    s = adjust_start(t, s0, max_probe=30)
    assert t[s - 1] == "，"


def test_overlap_floor_below_chunk_overlap_allows_smaller_actual_overlap() -> None:
    """
    重叠下界（overlap_floor）可小于 chunk_overlap：clamp 上界为 prev_end - floor，
    floor 较小时不必把起点左推到「至少 chunk_overlap」重叠。
    """
    # 与运行时日志一致：prev_end=18286、s_aligned=18225 时，重叠仅对齐已为 61
    assert _clamp_start_for_overlap(18225, 18286, 100) == 18186
    assert _clamp_start_for_overlap(18225, 18286, 60) == 18225


def test_overlap_must_be_less_than_size_boundary_aware() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        list(iter_text_slices_boundary_aware("ab", chunk_size=2, chunk_overlap=2))


def test_boundary_aware_constitution_excerpt_overlap_chunks_sentence_aligned() -> None:
    """
    回归：相邻块在重叠窗口处均应对齐句界。

    - 第一段：`adjust_end` 后右开终点前一字符须为句界截止符（不得以从句/短语中间截断）。
    - 第二段：不得以「的统一领导下…」半截开头（重叠上界曾误用 max 导致）。

    语料：tests/test_chunking/fixture_constitution_excerpt.txt（宪法节选，与用户调试时一致）。
    参数：chunk_size=1500, chunk_overlap=100，与预览默认量级一致。
    """
    text = (Path(__file__).resolve().parent / "fixture_constitution_excerpt.txt").read_text(
        encoding="utf-8"
    )
    chunks = list(
        iter_text_slices_boundary_aware(
            text,
            chunk_size=1500,
            chunk_overlap=100,
            max_probe=30,
        )
    )
    assert len(chunks) >= 2
    first_text, s0, e0 = chunks[0]
    assert e0 > s0
    assert text[e0 - 1] in BOUNDARY_CHARS, (
        "第一段结尾应对齐到句界截止符（adjust_end），不得以从句/短语中间截断"
    )
    assert first_text.rstrip()[-1] == text[e0 - 1], "首块文本尾部应与全局切片一致"
    second = chunks[1][0]
    stripped = second.lstrip()
    assert not stripped.startswith("的统一领导下"), (
        "第二块不应以依存短语半截开头；若失败请检查重叠上界 min(s, prev_end-overlap)"
    )
    # 弱边界可能改变第二块起点，不要求整句必在第二块前 200 字内；相邻块拼接须仍覆盖该表述
    assert "中央和地方的国家机构" in (first_text + second), (
        "相邻块拼接应仍含「中央和地方的国家机构」完整表述"
    )
