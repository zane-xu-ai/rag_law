#!/usr/bin/env python3
"""从 Elasticsearch 读出与 `data/*.md` 同名的各文件 chunk，写入 `tmp/`，每块一行，块间空一行，重叠段用中文着重号「【】」标出。

项目根执行::

    uv run python scripts/es_dump_chunks_to_tmp.py

需本机 ES、已入库；`tmp/` 已加入 `.gitignore`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def fetch_chunks_for_file(client: object, index: str, source_file: str) -> list[dict]:
    """按 `chunk_index` 升序返回 `_source` 列表。"""
    resp = client.search(
        index=index,
        query={"term": {"source_file": source_file}},
        sort=[{"chunk_index": "asc"}],
        size=10000,
    )
    hits = resp.get("hits", {}).get("hits", [])
    return [h.get("_source") or {} for h in hits]


def main() -> int:
    from argparse import ArgumentParser

    p = ArgumentParser(description="ES chunk 导出到 tmp/，与 data 文件名一致")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="用于枚举 *.md 文件名（默认 <项目根>/data）",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="输出目录（默认 <项目根>/tmp）",
    )
    args = p.parse_args()

    from conf.settings import get_settings, project_root
    from es_store.client import elasticsearch_client
    from ingest.dump_format import build_file_body

    get_settings.cache_clear()
    settings = get_settings()
    root = project_root()
    data_dir = args.data_dir if args.data_dir is not None else root / "data"
    out_dir = args.out_dir if args.out_dir is not None else root / "tmp"
    if not data_dir.is_dir():
        print("ERROR: 数据目录不存在:", data_dir, file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    client = elasticsearch_client(settings)
    if not client.ping():
        print("ERROR: ES ping 失败", file=sys.stderr)
        return 1

    md_files = sorted(data_dir.glob("*.md"))
    if not md_files:
        print("ERROR: 未找到 *.md:", data_dir, file=sys.stderr)
        return 1

    idx = settings.es_index
    total_chunks = 0
    files_written = 0
    for md in md_files:
        name = md.name
        srcs = fetch_chunks_for_file(client, idx, name)
        if not srcs:
            print("WARN: 索引中无 source_file=%r，跳过" % name, file=sys.stderr)
            continue
        body = build_file_body(srcs)
        out_path = out_dir / name
        out_path.write_text(body, encoding="utf-8")
        total_chunks += len(srcs)
        files_written += 1
        print("%s: %s 块 -> %s" % (name, len(srcs), out_path))

    print("共 %s 块，写入 %s 个文件于 %s" % (total_chunks, files_written, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
