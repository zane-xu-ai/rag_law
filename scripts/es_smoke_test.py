#!/usr/bin/env python3
"""Elasticsearch 读写冒烟：ping → 文本索引 match_all → dense_vector kNN → 删索引。

项目根执行::

    PYTHONPATH=src uv run python scripts/es_smoke_test.py
    PYTHONPATH=src uv run python scripts/es_smoke_test.py --keep-index

需本机 ES；可选 compose 见 `doc/storage/docker-compose.elasticsearch.yml`。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def _l2_norm(v: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in v))
    if s < 1e-12:
        return v[:]
    return [x / s for x in v]


def _hit_total(resp: dict) -> int:
    t = resp.get("hits", {}).get("total", 0)
    if isinstance(t, dict):
        return int(t.get("value", 0))
    return int(t)


def main() -> int:
    parser = argparse.ArgumentParser(description="ES 连通性与读写冒烟")
    parser.add_argument(
        "--index",
        default="rag_law_doc_smoke",
        help="kNN 测试用临时索引名",
    )
    parser.add_argument("--keep-index", action="store_true", help="不删除 kNN 测试索引")
    parser.add_argument(
        "--dims",
        type=int,
        default=4,
        help="kNN 测试向量维度（默认 4）",
    )
    args = parser.parse_args()

    if os.environ.get("PYTEST_CURRENT_TEST"):
        os.environ.pop("PYTEST_CURRENT_TEST", None)

    from conf.settings import get_settings
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore

    get_settings.cache_clear()
    settings = get_settings()
    client = elasticsearch_client(settings)

    print("1) ping")
    if not client.ping():
        print("ERROR: ES ping 失败", file=sys.stderr)
        return 1
    ver = client.info().get("version", {}).get("number", "?")
    print("   OK, version=", ver)

    # --- 纯文本路径（不依赖向量）---
    txt_index = args.index + "_txt"
    print("2) 文本索引", txt_index, "→ index → match_all → delete")
    if client.indices.exists(index=txt_index):
        client.indices.delete(index=txt_index)
    client.indices.create(
        index=txt_index,
        mappings={"properties": {"body": {"type": "text"}}},
    )
    client.index(index=txt_index, id="1", document={"body": "hello elasticsearch smoke"})
    client.indices.refresh(index=txt_index)
    r = client.search(index=txt_index, query={"match_all": {}})
    n = _hit_total(r)
    print("   match_all hits:", n)
    if n < 1:
        print("ERROR: 预期至少 1 条命中", file=sys.stderr)
        return 1
    client.indices.delete(index=txt_index)
    print("   文本路径 OK")

    # --- kNN 路径 ---
    dims = args.dims
    store = EsChunkStore(client, args.index, dense_dims=dims)
    print("3) kNN 索引", args.index, "dims=", dims)
    store.ensure_index(recreate=True)

    docs = [
        {
            "text": "示例 A",
            "embedding": _l2_norm([1.0, 0.0, 0.0, 1.0][:dims]),
            "source_file": "a.md",
            "source_path": "data/a.md",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 10,
        },
        {
            "text": "示例 B",
            "embedding": _l2_norm([0.0, 1.0, 0.0, 1.0][:dims]),
            "source_file": "b.md",
            "source_path": "data/b.md",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 10,
        },
    ]
    if dims < 2:
        print("ERROR: --dims 至少为 2", file=sys.stderr)
        return 1
    # 截断/填充到 dims
    for d in docs:
        e = d["embedding"]
        if len(e) < dims:
            e = e + [0.0] * (dims - len(e))
        else:
            e = e[:dims]
        d["embedding"] = _l2_norm(e)

    ok_n, errs = store.bulk_index_chunks(docs)
    if errs:
        print("ERROR bulk:", errs, file=sys.stderr)
        return 1
    print("   bulk indexed:", ok_n)
    store.refresh()
    q = _l2_norm([1.0, 0.0] + [0.0] * (dims - 2))
    hits = store.search_knn(q, k=2)
    print("   kNN hits:", len(hits))
    for h in hits:
        print("    ", h["id"], round(h["score"], 6), h["source"].get("text"))

    if not args.keep_index:
        print("4) 删除 kNN 索引", args.index)
        if client.indices.exists(index=args.index):
            client.indices.delete(index=args.index)
    else:
        print("4) 保留 kNN 索引 (--keep-index)")

    print("全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
