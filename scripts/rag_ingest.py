#!/usr/bin/env python3
"""MVP 入库：`data/*.md` → 切分 → BGE-M3 → Elasticsearch（默认全量 recreate 索引）。

**勿**命名为 `ingest.py`，以免与 `src/ingest` 包名冲突。

项目根执行::

    uv run python scripts/rag_ingest.py
    uv run python scripts/rag_ingest.py --dry-run
    uv run python scripts/rag_ingest.py --no-recreate

需：`uv sync --extra embedding`、本机 ES；compose 见 `doc/storage/docker-compose.elasticsearch.yml`。
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
    parser = argparse.ArgumentParser(description="RAG MVP：data 目录 Markdown 入库 ES")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Markdown 目录（默认 <项目根>/data）",
    )
    parser.add_argument(
        "--recreate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否删索引后重建（默认：是）",
    )
    parser.add_argument(
        "--boundary-aware",
        action="store_true",
        help="句边界对齐切分（默认关闭）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅统计块数，不加载模型、不连 ES",
    )
    parser.add_argument(
        "--smoke-query",
        type=str,
        default="宪法",
        help="入库后可选：kNN 抽检查询文本（默认「宪法」；设为空跳过）",
    )
    args = parser.parse_args()

    from conf.settings import get_settings
    from ingest import load_chunks_with_sha256
    from ingest.documents import chunk_embedding_to_source

    get_settings.cache_clear()
    settings = get_settings()

    print("1) 切分 + 每文件 SHA256 …")
    chunks, shas = load_chunks_with_sha256(
        args.data_dir,
        boundary_aware=args.boundary_aware,
    )
    n = len(chunks)
    print("   块数:", n)
    if n == 0:
        print("ERROR: 无 chunk，请检查 --data-dir 下是否有 *.md", file=sys.stderr)
        return 1

    if args.dry_run:
        print("   (--dry-run) 结束")
        return 0

    print("2) 向量编码 …")
    from embeddings import build_embedder

    embedder = build_embedder(settings)
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_documents(texts)
    if len(embeddings) != n:
        print("ERROR: 向量条数与块数不一致", file=sys.stderr)
        return 1
    dim = embedder.dense_dimension
    for i, row in enumerate(embeddings):
        if len(row) != dim:
            print("ERROR: 行 %s 维度异常" % i, file=sys.stderr)
            return 1

    print("3) 连接 ES …")
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore

    client = elasticsearch_client(settings)
    if not client.ping():
        print("ERROR: ES ping 失败", file=sys.stderr)
        return 1

    store = EsChunkStore(
        client,
        settings.es_index,
        dense_dims=dim,
    )
    store.ensure_index(recreate=args.recreate)

    print("4) bulk 写入 …")
    docs = [
        chunk_embedding_to_source(c, emb, source_sha256=sha)
        for c, emb, sha in zip(chunks, embeddings, shas)
    ]
    ok_n, errs = store.bulk_index_chunks(docs)
    if errs:
        print("ERROR bulk:", errs, file=sys.stderr)
        return 1
    print("   成功条数:", ok_n)

    store.refresh()
    cnt = client.count(index=settings.es_index)
    total = int(cnt["count"])
    print("5) count:", total)
    if total != n:
        print("ERROR: count 与块数不一致", file=sys.stderr)
        return 1

    if args.smoke_query.strip():
        print("6) kNN 抽检:", repr(args.smoke_query.strip()))
        qv = embedder.embed_query(args.smoke_query.strip())
        k = min(settings.retrieval_k, n)
        hits = store.search_knn(qv, k=k)
        for h in hits[:3]:
            src = h.get("source") or {}
            t = (src.get("text") or "")[:120].replace("\n", " ")
            print("   ", "score=%.4f" % h["score"], "id=%r" % h["id"], "|", t[:80], "…")

    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
