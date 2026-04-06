#!/usr/bin/env python3
"""
对单份 Markdown 做边界切分，统计 chunk 首尾是否在「句界字符」上完整，并输出原因分析。

用法（项目根目录）：
  PYTHONPATH=src uv run python scripts/analyze_boundary_chunk_integrity.py data/宪法.md \\
    --chunk-size 1500 --overlap 50 --overlap-floor 60 \\
    -o doc/chunk/宪法_边界切分完整性统计.md
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from chunking.boundary import (
    BOUNDARY_CHARS,
    DEFAULT_MAX_PROBE,
    _effective_max_boundary_scan,
    iter_boundary_aware_diag_rows,
)


def _diag_windows(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    max_probe: int,
    overlap_floor: int | None,
    overlap_ceiling: int | None,
    max_boundary_scan: int | None,
    boundary_priority_overlap: bool,
    clamp_adjust_max_rounds: int,
) -> list[dict]:
    """复现 `iter_text_slices_boundary_aware` 的每一步，并记录诊断字段。"""
    n = len(text)
    rows: list[dict] = []
    scan = _effective_max_boundary_scan(chunk_size, max_probe, max_boundary_scan)

    for row in iter_boundary_aware_diag_rows(
        text,
        chunk_size,
        chunk_overlap,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        max_probe=max_probe,
        max_boundary_scan=scan,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
    ):
        s_adj = row["s"]
        e_adj = row["e"]
        head_ok = s_adj == 0 or text[s_adj - 1] in BOUNDARY_CHARS
        tail_ok = e_adj == n or text[e_adj - 1] in BOUNDARY_CHARS
        rows.append(
            {
                "s0": row["s0"],
                "e0": row["e0"],
                "s": s_adj,
                "e": e_adj,
                "s_aligned": row["s_aligned"],
                "clamp_moved": row["clamp_moved"],
                "fallback": row["fallback"],
                "head_ok": head_ok,
                "tail_ok": tail_ok,
                "prev_end": row["prev_end"],
            }
        )
    return rows


def _reason_head(d: dict, text: str) -> str:
    if d["head_ok"]:
        return "—"
    s = d["s"]
    prev_ch = text[s - 1] if s > 0 else ""
    parts = []
    if d["fallback"]:
        parts.append("对齐坍缩后回退到原始滑窗，起点未保证在句界后")
    elif d["clamp_moved"]:
        parts.append(
            "重叠上界将起点左移，块首可能落在上一句中间（为满足与上一块至少达到 overlap_floor）"
        )
    if not d["fallback"] and s > 0 and prev_ch not in BOUNDARY_CHARS:
        if prev_ch in "，、":
            parts.append("前一字符为逗号/顿号：不在 BOUNDARY_CHARS（仅含 。！？；与换行）")
        elif prev_ch.strip() and prev_ch not in "\t ":
            parts.append(
                f"前一字符为 {prev_ch!r}：±{DEFAULT_MAX_PROBE} 内未找到更合适的句界起点，或平局策略保留当前位置"
            )
        else:
            parts.append("前一字符为空白，句界判定可能跨行/格式导致")
    return "；".join(parts) if parts else "（未归类）"


def _reason_tail(d: dict, text: str) -> str:
    if d["tail_ok"]:
        return "—"
    n = len(text)
    e = d["e"]
    last = text[e - 1] if e > 0 else ""
    parts = []
    if d["fallback"]:
        parts.append("对齐坍缩后回退到原始滑窗，终点未保证落在句界字符上")
    if last in "，、":
        parts.append("块末为逗号/顿号：当前句界集合不含「，」「、」，语义上常为半句，但规则判定为尾不完整")
    elif last not in BOUNDARY_CHARS and not d["fallback"]:
        parts.append(
            f"块末字符为 {last!r}：adjust_end 在 ±{DEFAULT_MAX_PROBE} 内未找到句界，或平局策略未推到句号等"
        )
    return "；".join(parts) if parts else "（未归类）"


def main() -> None:
    p = argparse.ArgumentParser(description="边界切分 chunk 首尾完整性统计")
    p.add_argument("md_path", type=Path, help="Markdown 文件路径")
    p.add_argument("--chunk-size", type=int, default=1500)
    p.add_argument("--overlap", type=int, default=50)
    p.add_argument("--max-probe", type=int, default=DEFAULT_MAX_PROBE)
    p.add_argument(
        "--overlap-floor",
        type=int,
        default=None,
        help="块链重叠下界（默认等于 --overlap，对应 CHUNK_OVERLAP_MIN）",
    )
    p.add_argument(
        "--overlap-ceiling",
        type=int,
        default=None,
        help="块链重叠上界（默认等于 --overlap，对应 CHUNK_OVERLAP_MAX）",
    )
    p.add_argument(
        "--max-boundary-scan",
        type=int,
        default=None,
        help="扩展扫描半径（默认 min(chunk_size, 800)）",
    )
    p.add_argument(
        "--boundary-priority-overlap",
        action="store_true",
        help="句首对齐优先于重叠区间（允许实际重叠越界）",
    )
    p.add_argument(
        "--clamp-adjust-max-rounds",
        type=int,
        default=2,
        help="夹紧与句首二次对齐最大往返轮数（默认 2）",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="写入 Markdown 报告路径（默认只打印到 stdout）",
    )
    args = p.parse_args()

    text = args.md_path.read_text(encoding="utf-8")
    n = len(text)
    rows = _diag_windows(
        text,
        args.chunk_size,
        args.overlap,
        args.max_probe,
        args.overlap_floor,
        args.overlap_ceiling,
        args.max_boundary_scan,
        args.boundary_priority_overlap,
        args.clamp_adjust_max_rounds,
    )

    head_bad = [r for r in rows if not r["head_ok"]]
    tail_bad = [r for r in rows if not r["tail_ok"]]
    both_bad = [r for r in rows if not r["head_ok"] and not r["tail_ok"]]

    overlaps_actual: list[int] = []
    for r in rows:
        pe = r["prev_end"]
        if pe is not None:
            overlaps_actual.append(pe - r["s"])

    lines: list[str] = []
    lines.append(f"# 边界切分首尾完整性：{args.md_path.name}\n")
    lines.append("## 分析过程\n\n")
    lines.append(
        "1. 使用与 `chunking.boundary.iter_text_slices_boundary_aware` 一致的步骤："
        "先 `iter_text_slices` 得滑窗初值 `(s0,e0)`，再 `adjust_start_extended` / `adjust_end_extended`（强→弱→初值，扩展扫描），"
        "重叠夹紧后再对句首做二次扩展对齐与协调；重叠区间 `[overlap_floor, overlap_ceiling]`（默认均等于 `chunk_overlap`）。\n"
    )
    lines.append(
        "2. 对每一块检查：`s==0` 或 `text[s-1]` 为句界则**首完整**；"
        "`e==len(text)` 或 `text[e-1]` 为句界则**尾完整**（句界见下方 `BOUNDARY_CHARS`）。\n"
    )
    lines.append(
        "3. 本报告由 `scripts/analyze_boundary_chunk_integrity.py` 生成；"
        "相邻块实际重叠长度为 `上一块 char_end - 本块 char_start`（与预览 `overlap_between_adjacent` 一致）。\n"
    )
    lines.append(
        f"\n- **生成时间（UTC）**：`{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}`\n"
    )
    out_arg = ""
    if args.output is not None:
        out_arg = f" -o {args.output.as_posix()}"
    lines.append(
        "- **生成命令**：`PYTHONPATH=src uv run python scripts/analyze_boundary_chunk_integrity.py "
        f"{args.md_path.as_posix()} --chunk-size {args.chunk_size} --overlap {args.overlap}"
        + (
            f" --overlap-floor {args.overlap_floor}" if args.overlap_floor is not None else ""
        )
        + (
            f" --overlap-ceiling {args.overlap_ceiling}"
            if args.overlap_ceiling is not None
            else ""
        )
        + f" --max-probe {args.max_probe}"
        + (
            f" --max-boundary-scan {args.max_boundary_scan}"
            if args.max_boundary_scan is not None
            else ""
        )
        + (" --boundary-priority-overlap" if args.boundary_priority_overlap else "")
        + f" --clamp-adjust-max-rounds {args.clamp_adjust_max_rounds}"
        + f"{out_arg}`\n"
    )

    lines.append("\n## 参数\n")
    lines.append(f"- 文件字符数：`{n}`\n")
    of = args.overlap_floor if args.overlap_floor is not None else args.overlap
    oc = args.overlap_ceiling if args.overlap_ceiling is not None else args.overlap
    mbs = _effective_max_boundary_scan(args.chunk_size, args.max_probe, args.max_boundary_scan)
    lines.append(
        f"- `chunk_size`={args.chunk_size}, `chunk_overlap`={args.overlap}, "
        f"`overlap_floor`={of}, `overlap_ceiling`={oc}, `max_probe`={args.max_probe}, "
        f"`max_boundary_scan`={mbs}, `boundary_priority_overlap`={args.boundary_priority_overlap}, "
        f"`clamp_adjust_max_rounds`={args.clamp_adjust_max_rounds}\n"
    )
    lines.append(f"- 句界字符集：`{''.join(sorted(BOUNDARY_CHARS))!r}`（不含逗号、顿号）\n")
    lines.append("\n## 判定\n\n")
    lines.append("- **首完整**：`s==0` 或 `text[s-1]` 属于句界字符（块从句界之后开始）。\n")
    lines.append("- **尾完整**：`e==len(text)` 或 `text[e-1]` 属于句界字符。\n")
    lines.append("\n## 汇总\n\n")
    lines.append("| 指标 | 数量 |\n| --- | ---: |\n")
    lines.append(f"| chunk 总数 | {len(rows)} |\n")
    lines.append(f"| 首不完整 | {len(head_bad)} |\n")
    lines.append(f"| 尾不完整 | {len(tail_bad)} |\n")
    lines.append(f"| 首尾均不完整 | {len(both_bad)} |\n")
    lines.append(f"| 发生过对齐回退（fallback）的块 | {sum(1 for r in rows if r['fallback'])} |\n")
    lines.append(
        f"| 起点被重叠上界左移（clamp）的块 | {sum(1 for r in rows if r['clamp_moved'])} |\n"
    )

    lines.append("\n## 相邻块实际重叠\n\n")
    if overlaps_actual:
        lines.append(
            f"- 各相邻对重叠长度：`{overlaps_actual}`\n"
        )
        lines.append(
            f"- min={min(overlaps_actual)}，max={max(overlaps_actual)}，"
            f"avg={round(sum(overlaps_actual) / len(overlaps_actual), 2)}（单位：字符）\n"
        )
        of = args.overlap_floor if args.overlap_floor is not None else args.overlap
        oc = args.overlap_ceiling if args.overlap_ceiling is not None else args.overlap
        lines.append(
            f"- 与 `overlap_floor={of}`、`overlap_ceiling={oc}` 的关系：实际重叠应在 **[{of}, {oc}]** 内"
            "（起点经句界对齐后由 `_clamp_start_to_overlap_range` 夹紧）；"
            "若窗口内无法同时满足句界与区间，可能回退初值或产生更短块。\n"
        )
    else:
        lines.append("- 仅一块或无相邻对。\n")

    lines.append("\n## 不完整 chunk 明细与原因\n\n")
    incomplete = [
        (i, r)
        for i, r in enumerate(rows)
        if not r["head_ok"] or not r["tail_ok"]
    ]
    if not incomplete:
        lines.append("无：所有 chunk 首尾均满足当前句界规则。\n")
    else:
        for idx, r in incomplete:
            piece = text[r["s"] : r["e"]]
            head_snip = piece[:80].replace("\n", "\\n")
            tail_snip = piece[-80:].replace("\n", "\\n")
            lines.append(f"### chunk 索引 {idx}（全局切片 `[{r['s']}, {r['e']})`）\n\n")
            lines.append(f"- 首完整：{r['head_ok']}；尾完整：{r['tail_ok']}\n")
            lines.append(f"- fallback：{r['fallback']}；重叠导致起点左移：{r['clamp_moved']}\n")
            lines.append(f"- 首不完整原因：{_reason_head(r, text)}\n")
            lines.append(f"- 尾不完整原因：{_reason_tail(r, text)}\n")
            lines.append("\n块首预览：\n\n```text\n")
            lines.append(head_snip + "\n```\n\n")
            lines.append("块尾预览：\n\n```text\n")
            lines.append(tail_snip + "\n```\n\n")

    report = "".join(lines)
    print(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"\n[已写入] {args.output}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
