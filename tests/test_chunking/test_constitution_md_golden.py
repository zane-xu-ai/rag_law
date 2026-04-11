"""《宪法》MinerU 正文与方案 C（c03_breakpoint）导出黄金回归。

语料：`tests/test_chunking/fixtures/宪法.md`（与 `data/md_minerU/md3__宪法.md` 同步提交）。

基准导出：`fixtures/宪法_c03_breakpoint_export.md`（与 `data/chunk_md/c03_breakpoint/md3__宪法.md` 同步），
按 :func:`chunking.breakpoint_embed.split_breakpoint_export_to_chunks` 拆块后，区间与
`fixtures/宪法_c03_breakpoint_golden.json` 一致。用于与方案 D 分段结果对比时的固定参照。

**何时更新 fixture**：MinerU 源文或 c03 导出参数（窗长、阈值、max_chars 等）变更后，同步更新三件套并注明 PR。
"""

from __future__ import annotations

import json
from pathlib import Path

from chunking.breakpoint_embed import split_breakpoint_export_to_chunks

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_CONSTITUTION_PATH = _FIXTURES / "宪法.md"
_EXPORT_PATH = _FIXTURES / "宪法_c03_breakpoint_export.md"
_GOLDEN_PATH = _FIXTURES / "宪法_c03_breakpoint_golden.json"


def _load_golden() -> dict:
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _ranges_from_source_and_chunks(source: str, chunks: list[str]) -> list[tuple[int, int]]:
    pos = 0
    out: list[tuple[int, int]] = []
    for c in chunks:
        L = len(c)
        out.append((pos, pos + L))
        pos += L
    assert pos == len(source), "块拼接长度与源文不一致"
    return out


def test_constitution_c03_export_matches_source_and_golden() -> None:
    golden = _load_golden()
    text = _CONSTITUTION_PATH.read_text(encoding="utf-8")
    export = _EXPORT_PATH.read_text(encoding="utf-8")
    parts = split_breakpoint_export_to_chunks(export)

    assert "".join(parts) == text, "去掉分隔条后应与 fixtures/宪法.md 逐字一致"
    assert len(text) == golden["total_chars"]
    assert len(parts) == golden["chunk_count"]

    got_ranges = _ranges_from_source_and_chunks(text, parts)
    expected_ranges = [tuple(pair) for pair in golden["ranges"]]
    assert got_ranges == expected_ranges, (
        "区间与黄金数据不一致；若有意更新 c03 导出，请同步 fixtures/宪法.md、"
        "宪法_c03_breakpoint_export.md、宪法_c03_breakpoint_golden.json"
    )

    lengths = [e - s for s, e in got_ranges]
    assert lengths == golden["chars_per_chunk"]


def test_constitution_c03_chunks_no_overlap_adjacent() -> None:
    """方案 C 默认 split_overlap=0，相邻块首尾相接，无重叠。"""
    text = _CONSTITUTION_PATH.read_text(encoding="utf-8")
    parts = split_breakpoint_export_to_chunks(_EXPORT_PATH.read_text(encoding="utf-8"))
    ranges = _ranges_from_source_and_chunks(text, parts)
    for i in range(1, len(ranges)):
        assert ranges[i - 1][1] == ranges[i][0], f"相邻块应对齐接合，索引 {i - 1}/{i}"
