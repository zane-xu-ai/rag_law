#!/usr/bin/env python3
"""方案 C（嵌入断点）：对本地 Markdown 做断点切分，写入 ``data/chunk_md/c03_breakpoint/``。

块与块之间使用 ``chunking.breakpoint_embed.default_chunk_separator()`` 分隔（极醒目纯文本）。

项目根执行::

    uv run python scripts/c03_breakpoint_export.py
    uv run python scripts/c03_breakpoint_export.py --files data/md_minerU/md3__宪法.md
    uv run python scripts/c03_breakpoint_export.py --data-dir data/md_minerU --limit 2
    uv run python scripts/c03_breakpoint_export.py --files data/md_minerU/md3__宪法.md --no-progress

需：``uv sync --extra embedding``；``.env`` 中 ``BGE_M3_PATH`` 等。按文件显示 tqdm 进度条（可用 ``--no-progress`` 关闭）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="方案 C 嵌入断点切分 → data/chunk_md/c03_breakpoint")
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="目录下全部 *.md（与 rag_ingest 类似）",
    )
    src.add_argument(
        "--files",
        type=Path,
        nargs="+",
        help="指定若干 .md 路径（相对项目根或绝对）",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "data" / "chunk_md" / "c03_breakpoint",
        help="输出目录（默认 data/chunk_md/c03_breakpoint）",
    )
    parser.add_argument("--window", type=int, default=256, help="编码窗长（字符）")
    parser.add_argument("--stride", type=int, default=128, help="窗步长（字符）")
    parser.add_argument(
        "--sim-threshold",
        type=float,
        default=0.72,
        help="相邻窗余弦低于此值则记断点（0–1）",
    )
    parser.add_argument("--min-chars", type=int, default=200, help="合并后段最小目标长度")
    parser.add_argument("--max-chars", type=int, default=2200, help="超长段再滑窗劈分上限")
    parser.add_argument(
        "--split-overlap",
        type=int,
        default=0,
        help="超长段二次滑窗重叠；默认 0 使导出拼接无重复（与入库滑窗重叠不同）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="与 --data-dir 联用：最多处理前 N 个 md（字典序）",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="禁用按文件 tqdm 进度条（Embedding 内部进度不受影响）",
    )
    args = parser.parse_args()

    from conf.logging_setup import configure_logging
    from conf.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings)

    if args.files:
        paths = []
        for p in args.files:
            rp = (_ROOT / p).resolve() if not p.is_absolute() else p.resolve()
            if not rp.is_file():
                print("ERROR: 不是文件:", rp, file=sys.stderr)
                return 1
            if rp.suffix.lower() != ".md":
                print("ERROR: 仅支持 .md:", rp, file=sys.stderr)
                return 1
            paths.append(rp)
        paths = sorted(paths)
    elif args.data_dir:
        base = (_ROOT / args.data_dir).resolve() if not args.data_dir.is_absolute() else args.data_dir.resolve()
        if not base.is_dir():
            print("ERROR: 目录不存在:", base, file=sys.stderr)
            return 1
        paths = sorted(base.glob("*.md"))
        if args.limit is not None:
            paths = paths[: max(0, args.limit)]
    else:
        default_dir = _ROOT / "data" / "md_minerU"
        if not default_dir.is_dir():
            print("ERROR: 请指定 --data-dir 或 --files", file=sys.stderr)
            return 1
        paths = sorted(default_dir.glob("*.md"))

    if not paths:
        print("ERROR: 无 .md 文件", file=sys.stderr)
        return 1

    from embeddings import build_embedder

    embedder = build_embedder(settings)

    from chunking.breakpoint_embed import export_breakpoint_chunks_dir

    written = export_breakpoint_chunks_dir(
        paths,
        args.out_dir,
        embedder,
        window_chars=args.window,
        stride_chars=args.stride,
        sim_threshold=args.sim_threshold,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        split_overlap=args.split_overlap,
        progress=not args.no_progress,
    )
    for w in written:
        print("写入:", w.relative_to(_ROOT))
    print("完成，共", len(written), "个文件 →", args.out_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
