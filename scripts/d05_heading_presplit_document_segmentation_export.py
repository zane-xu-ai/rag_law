#!/usr/bin/env python3
"""v1.1.10：Markdown 标题递归预切分 + 段内方案 D，写入 ``data/chunk_md/d05_heading_presplit_document_segmentation/``。

块分隔条见 ``chunking.md_heading_presplit.default_heading_presplit_separator()``。

项目根执行::

    uv sync --extra segmentation
    uv run python scripts/d05_heading_presplit_document_segmentation_export.py
    uv run python scripts/d05_heading_presplit_document_segmentation_export.py --files data/md_minerU/md3__宪法.md
    uv run python scripts/d05_heading_presplit_document_segmentation_export.py --name-contains 婚姻法

与 ``d04_document_segmentation_export.py`` 相同：``--data-dir`` / ``--files`` / 默认 ``data/md_minerU``、
``--out-dir``、``--model-path`` 或 ``DOCUMENT_SEGMENTATION_PATH``、``--min-chars`` / ``--max-chars`` /
``--split-overlap``（未传读 ``DOC_SEGMENTATION_*``）。

标题策略未传时读 ``.env``：``CHUNK_MD_HEADING_STRATEGY``、``CHUNK_MD_HEADING_FIXED_LEVEL``、
``CHUNK_MD_HEADING_SINGLE_IMMEDIATE_CHILD``。叶子超长阈值：``--section-max-chars`` 或
``DOC_SEGMENTATION_SECTION_MAX_CHARS``（未设则等于 ``max_chars``）。
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
    parser = argparse.ArgumentParser(
        description="v1.1.10 标题预切分 + 方案 D → data/chunk_md/d05_heading_presplit_document_segmentation"
    )
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument("--data-dir", type=Path, default=None, help="目录下全部 *.md")
    src.add_argument("--files", type=Path, nargs="+", help="指定若干 .md 路径（相对项目根或绝对）")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "data" / "chunk_md" / "d05_heading_presplit_document_segmentation",
        help="输出目录（默认 data/chunk_md/d05_heading_presplit_document_segmentation）",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="document-segmentation 模型目录；不设则用 DOCUMENT_SEGMENTATION_PATH",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=None,
        help="段内 D：合并过短段阈值；不传读 DOC_SEGMENTATION_MIN_CHARS",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="段内 D：超长再切上限；不传读 DOC_SEGMENTATION_MAX_CHARS",
    )
    parser.add_argument(
        "--split-overlap",
        type=int,
        default=None,
        help="段内 D：重叠；不传读 DOC_SEGMENTATION_SPLIT_OVERLAP",
    )
    parser.add_argument(
        "--section-max-chars",
        type=int,
        default=None,
        help="标题叶子超过该字数才在段内跑 D；不传读 DOC_SEGMENTATION_SECTION_MAX_CHARS，再否则等于 max_chars",
    )
    parser.add_argument(
        "--heading-strategy",
        type=str,
        default=None,
        choices=("deepest_with_multiple", "shallowest_with_multiple", "none"),
        help="标题预切分策略；不传读 CHUNK_MD_HEADING_STRATEGY",
    )
    parser.add_argument(
        "--heading-fixed-level",
        type=int,
        default=None,
        help="首轮强制 ATX 层级 1..6；不传读 CHUNK_MD_HEADING_FIXED_LEVEL（可空）",
    )
    parser.add_argument(
        "--heading-single-child",
        type=str,
        default=None,
        choices=("strict", "relaxed"),
        help="单子级标题是否停止细分；不传读 CHUNK_MD_HEADING_SINGLE_IMMEDIATE_CHILD",
    )
    parser.add_argument("--limit", type=int, default=None, help="与 --data-dir 联用：最多前 N 个 md")
    parser.add_argument(
        "--name-contains",
        metavar="SUBSTR",
        default=None,
        help="只处理文件名包含该子串的 .md",
    )
    parser.add_argument("--no-progress", action="store_true", help="禁用按文件 tqdm")
    args = parser.parse_args()

    from conf.logging_setup import configure_logging
    from conf.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings)

    if args.model_path is not None:
        p = args.model_path
        mp = p.resolve() if p.is_absolute() else (_ROOT / p).resolve()
    else:
        env_mp = settings.document_segmentation_path
        if not env_mp:
            print(
                "ERROR: 请设置 --model-path 或 .env 中 DOCUMENT_SEGMENTATION_PATH",
                file=sys.stderr,
            )
            return 1
        mp = Path(env_mp).expanduser().resolve()

    if not mp.is_dir():
        print("ERROR: 模型目录不存在:", mp, file=sys.stderr)
        return 1

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

    if args.name_contains:
        paths = [p for p in paths if args.name_contains in p.name]
        if not paths:
            print("ERROR: --name-contains 无匹配:", repr(args.name_contains), file=sys.stderr)
            return 1

    if not paths:
        print("ERROR: 无 .md 文件", file=sys.stderr)
        return 1

    from chunking.document_segmentation import build_document_segmentation_pipeline
    from chunking.md_heading_presplit import export_heading_presplit_document_segmentation_dir

    try:
        pipe = build_document_segmentation_pipeline(mp)
    except ImportError as e:
        print("ERROR:", e, file=sys.stderr)
        return 1

    min_chars = (
        settings.doc_segmentation_min_chars if args.min_chars is None else args.min_chars
    )
    max_chars = (
        settings.doc_segmentation_max_chars if args.max_chars is None else args.max_chars
    )
    split_overlap = (
        settings.doc_segmentation_split_overlap
        if args.split_overlap is None
        else args.split_overlap
    )
    section_max = (
        settings.doc_segmentation_section_max_chars
        if args.section_max_chars is None
        else args.section_max_chars
    )
    if section_max is None:
        section_max = max_chars

    if split_overlap >= max_chars:
        print(
            "ERROR: split_overlap 须小于 max_chars（当前 max_chars=%s split_overlap=%s）"
            % (max_chars, split_overlap),
            file=sys.stderr,
        )
        return 1

    strategy = (
        settings.chunk_md_heading_strategy
        if args.heading_strategy is None
        else args.heading_strategy
    )
    fixed_lv = (
        settings.chunk_md_heading_fixed_level
        if args.heading_fixed_level is None
        else args.heading_fixed_level
    )
    single_child = (
        settings.chunk_md_heading_single_immediate_child
        if args.heading_single_child is None
        else args.heading_single_child
    )

    print(
        "d05 参数: heading_strategy=%s heading_fixed_level=%s heading_single_child=%s"
        % (strategy, fixed_lv, single_child)
    )
    print(
        "d05 段内 D: min_chars=%s max_chars=%s split_overlap=%s section_max_chars=%s"
        % (min_chars, max_chars, split_overlap, section_max)
    )

    written = export_heading_presplit_document_segmentation_dir(
        paths,
        args.out_dir,
        pipe,
        strategy=strategy,
        fixed_first_level=fixed_lv,
        single_immediate_child=single_child,
        min_chars=min_chars,
        max_chars=max_chars,
        split_overlap=split_overlap,
        section_max_chars=section_max,
        progress=not args.no_progress,
    )
    for w in written:
        print("写入:", w.relative_to(_ROOT))
    print("完成，共", len(written), "个文件 →", args.out_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
