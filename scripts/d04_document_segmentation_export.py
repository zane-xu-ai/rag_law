#!/usr/bin/env python3
"""方案 D（文档分段模型）：对本地 Markdown 做分段切分，写入 ``data/chunk_md/d04_document_segmentation/``。

块分隔条见 ``chunking.document_segmentation.default_document_segmentation_separator()``。

项目根执行::

    uv sync --extra segmentation
    uv run python scripts/d04_document_segmentation_export.py --model-path /path/to/nlp_bert_document-segmentation_chinese-base
    # 或依赖 .env 中 DOCUMENT_SEGMENTATION_PATH
    uv run python scripts/d04_document_segmentation_export.py --files data/md_minerU/md3__宪法.md
    # 只导出文件名含「婚姻法」的 md（默认扫 data/md_minerU/）
    uv run python scripts/d04_document_segmentation_export.py --name-contains 婚姻法

需：``uv sync --extra segmentation``（会装齐 modelscope、torch、Pillow 等，避免仅装 modelscope 仍无法 ``import modelscope.pipelines``）。
本地已下载的 ModelScope 文档分段模型目录；``.env`` 可配置 ``DOCUMENT_SEGMENTATION_PATH``（与 ``--model-path`` 二选一必填）。

未传 ``--min-chars`` / ``--max-chars`` / ``--split-overlap`` 时，使用 ``.env`` 中
``DOC_SEGMENTATION_MIN_CHARS``、``DOC_SEGMENTATION_MAX_CHARS``、``DOC_SEGMENTATION_SPLIT_OVERLAP``
（见 ``conf.settings`` 默认值）。命令行参数始终优先。
``CHUNK_DOC_SEGMENTATION_ENABLED`` 仅预留接入 ingest，**不影响** 本导出脚本。
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
        description="方案 D 文档分段模型 → data/chunk_md/d04_document_segmentation"
    )
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="目录下全部 *.md",
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
        default=_ROOT / "data" / "chunk_md" / "d04_document_segmentation",
        help="输出目录（默认 data/chunk_md/d04_document_segmentation）",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="document-segmentation 模型目录（若不设，则使用环境变量 DOCUMENT_SEGMENTATION_PATH）",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=None,
        help="合并过短段阈值；不传则读 .env 的 DOC_SEGMENTATION_MIN_CHARS（默认 0）",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="超长再切上限；不传则读 .env 的 DOC_SEGMENTATION_MAX_CHARS（默认 1200）",
    )
    parser.add_argument(
        "--split-overlap",
        type=int,
        default=None,
        help="超长再切重叠；不传则读 .env 的 DOC_SEGMENTATION_SPLIT_OVERLAP",
    )
    parser.add_argument("--limit", type=int, default=None, help="与 --data-dir 联用：最多前 N 个 md")
    parser.add_argument(
        "--name-contains",
        metavar="SUBSTR",
        default=None,
        help="只处理「文件名」包含该子串的 .md（默认目录、--data-dir 或 --files 列出后再筛选）",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="禁用按文件 tqdm",
    )
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

    from chunking.document_segmentation import build_document_segmentation_pipeline, export_document_segmentation_chunks_dir

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
    if split_overlap >= max_chars:
        print(
            "ERROR: split_overlap 须小于 max_chars（当前 max_chars=%s split_overlap=%s）"
            % (max_chars, split_overlap),
            file=sys.stderr,
        )
        return 1
    print(
        "d04 参数: min_chars=%s max_chars=%s split_overlap=%s"
        % (min_chars, max_chars, split_overlap)
    )

    written = export_document_segmentation_chunks_dir(
        paths,
        args.out_dir,
        pipe,
        min_chars=min_chars,
        max_chars=max_chars,
        split_overlap=split_overlap,
        progress=not args.no_progress,
    )
    for w in written:
        print("写入:", w.relative_to(_ROOT))
    print("完成，共", len(written), "个文件 →", args.out_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
