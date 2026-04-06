"""《宪法》正文在固定参数下的切分黄金回归。

语料来源：已提交副本 `tests/test_chunking/fixtures/宪法.md`（与本地 `data/宪法.md` 应对齐；`data/` 被 gitignore，CI 不依赖该目录）。

与 `chunking.webui` 句边界预览（及 `doc/chunk/宪法_边界切分完整性统计.md` 等价命令行）对齐：

- **chunk_size=1500**, **chunk_overlap=100**
- **boundary_aware=True**
- **overlap_floor=100**, **overlap_ceiling=100**（刚性重叠区间）
- **boundary_priority_overlap=True**（与预览在刚性重叠时自动开启一致）

黄金数据见 `tests/test_chunking/fixtures/宪法_1500_100_boundary_golden.json`。

**何时更新 fixture**：有意修改 `chunking.boundary` / `chunking.split` 的切分算法时，同步重跑本用例并更新 JSON
（commit/PR 中注明）；若仅 `fixtures/宪法.md` 正文变更导致失败，需按新正文重新生成黄金数据。
"""

from __future__ import annotations

import json
from pathlib import Path

from chunking.split import iter_chunks_for_text

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_CONSTITUTION_PATH = _FIXTURES / "宪法.md"
_GOLDEN_PATH = _FIXTURES / "宪法_1500_100_boundary_golden.json"


def _load_golden() -> dict:
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _slice_constitution() -> list:
    text = _CONSTITUTION_PATH.read_text(encoding="utf-8")
    return list(
        iter_chunks_for_text(
            text,
            source_file="宪法.md",
            source_path="tests/test_chunking/fixtures/宪法.md",
            chunk_size=1500,
            chunk_overlap=100,
            boundary_aware=True,
            overlap_floor=100,
            overlap_ceiling=100,
            boundary_priority_overlap=True,
        )
    )


def test_constitution_md_golden_ranges_match_chunking() -> None:
    golden = _load_golden()
    text = _CONSTITUTION_PATH.read_text(encoding="utf-8")
    chunks = _slice_constitution()

    assert len(text) == golden["total_chars"]
    assert len(chunks) == golden["chunk_count"]
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)

    got_ranges = [(c.char_start, c.char_end) for c in chunks]
    expected_ranges = [tuple(pair) for pair in golden["ranges"]]
    assert got_ranges == expected_ranges, (
        "切分区间与黄金数据不一致；若算法变更有意，请更新 fixtures/宪法_1500_100_boundary_golden.json"
    )

    lengths = [c.char_end - c.char_start for c in chunks]
    assert lengths == golden["chars_per_chunk"]


def test_constitution_md_golden_adjacent_overlaps_consistent() -> None:
    """相邻块重叠 = 上一块 char_end - 本块 char_start，与 preview_logic 一致。"""
    chunks = _slice_constitution()
    for i in range(1, len(chunks)):
        o = chunks[i - 1].char_end - chunks[i].char_start
        assert o > 0, f"相邻对 {i-1}/{i} 重叠应为正"
