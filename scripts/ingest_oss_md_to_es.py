#!/usr/bin/env python3
"""从阿里云 OSS 列举前缀下全部 ``.md`` → 下载到本地 → 切分 → BGE → 写入 ES（默认全量替换索引）。

默认：**桶名 ``rag-law``**，**对象前缀 ``md3/``**（即该桶内 ``md3/`` 目录下全部 ``*.md``，无条数上限）；下载目录 ``data/md_minerU``；每条 chunk 写入 ``source_oss_url``（虚拟主机样式公网 URL）。

项目根执行::

    uv sync --extra oss --extra embedding --extra es
    uv run python scripts/ingest_oss_md_to_es.py
    uv run python scripts/ingest_oss_md_to_es.py --bucket rag-law --prefix md3/
    uv run python scripts/ingest_oss_md_to_es.py --limit 50
    uv run python scripts/ingest_oss_md_to_es.py --dry-run

环境变量（与 ``conf.settings`` / ``utils/oss_aliyun/client.py`` 一致）：``OSS_ACCESS_KEY_ID``、``OSS_ACCESS_KEY_SECRET``、``OSS_REGION``；可选 ``OSS_ENDPOINT``、``OSS_BUCKET``、``OSS_OBJECT_PREFIX``、``OSS_DOWNLOAD_DIR``（见 ``Settings`` 默认值）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def _select_md_keys(all_keys: list[str], *, limit: int | None) -> list[str]:
    md_sorted = sorted(k for k in all_keys if k.lower().endswith(".md"))
    if limit is None:
        return md_sorted
    return md_sorted[:limit]


def main() -> int:
    from conf.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    if settings.oss_endpoint:
        os.environ.setdefault("OSS_ENDPOINT", settings.oss_endpoint)

    _dl_default = Path(settings.oss_download_dir)
    if not _dl_default.is_absolute():
        _dl_default = (_ROOT / _dl_default).resolve()

    parser = argparse.ArgumentParser(
        description="OSS Markdown → 本地 → 切分 → 向量 → Elasticsearch（含 source_oss_url）",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=settings.oss_bucket,
        help="OSS 桶名（默认来自 Settings / 环境变量 OSS_BUCKET）",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=settings.oss_object_prefix,
        help="列举对象时的 key 前缀（默认来自 Settings / OSS_OBJECT_PREFIX，自动补 /）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="可选：仅处理按 key 字典序的前 N 个 .md；不传则处理前缀下全部 .md",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=_dl_default,
        help="下载目录（默认来自 Settings / OSS_DOWNLOAD_DIR）",
    )
    parser.add_argument(
        "--recreate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否删索引后重建（默认：是，用于替换现有 chunk）",
    )
    parser.add_argument(
        "--boundary-aware",
        action="store_true",
        help="句边界对齐切分；未指定时采用 .env 的 CHUNK_BOUNDARY_AWARE",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列举与统计，不下载、不连模型与 ES",
    )
    parser.add_argument(
        "--smoke-query",
        type=str,
        default="宪法",
        help="入库后可选：kNN 抽检查询文本（设为空跳过）",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 须为 >= 1 的整数")

    from conf.logging_setup import configure_logging
    from ingest import load_chunks_with_sha256
    from ingest.documents import chunk_embedding_to_source
    from ingest.oss_layout import local_md_filename_for_oss_key
    from utils.oss_aliyun.crud import download_object_to_file, list_all_object_keys
    from utils.oss_aliyun.public_urls import oss_virtual_host_public_url

    configure_logging(settings)

    print("0) 列举 OSS 对象 …")
    try:
        all_keys = list_all_object_keys(args.bucket, prefix=args.prefix)
    except Exception as exc:
        print("ERROR: 列举 OSS 失败:", exc, file=sys.stderr)
        return 1

    md_keys = _select_md_keys(all_keys, limit=args.limit)
    if not md_keys:
        print(
            "ERROR: 未找到 .md 对象（请检查桶、前缀与权限）",
            file=sys.stderr,
        )
        return 1
    print("   选用 %s 个 Markdown key：" % len(md_keys))
    for k in md_keys:
        print("   -", k)

    if args.dry_run:
        print("   (--dry-run) 结束")
        return 0

    region = (settings.oss_region or os.getenv("OSS_REGION") or "").strip()
    if not region:
        print("ERROR: 需设置 OSS_REGION（.env 或环境变量）", file=sys.stderr)
        return 1

    download_dir = args.download_dir.expanduser()
    if not download_dir.is_absolute():
        download_dir = (_ROOT / download_dir).resolve()
    else:
        download_dir = download_dir.resolve()

    url_by_source_path: dict[str, str] = {}
    md_paths: list[Path] = []

    print("1) 下载到", download_dir)
    for key in md_keys:
        local = download_dir / local_md_filename_for_oss_key(key)
        try:
            download_object_to_file(args.bucket, key, local)
        except Exception as exc:
            print("ERROR: 下载失败 %s: %s" % (key, exc), file=sys.stderr)
            return 1
        try:
            rel = local.resolve().relative_to(_ROOT.resolve())
            sp = rel.as_posix()
        except ValueError:
            sp = str(local.resolve())
        url_by_source_path[sp] = oss_virtual_host_public_url(args.bucket, region, key)
        md_paths.append(local)

    print("2) 切分 + 每文件 SHA256 …")
    eff_ba = args.boundary_aware or settings.chunk_boundary_aware
    print(
        "   切分配置: CHUNK_SIZE=%s CHUNK_OVERLAP=%s CHUNK_BOUNDARY_AWARE=%s "
        "CHUNK_SEMANTIC_MERGE_ENABLED=%s"
        % (
            settings.chunk_size,
            settings.chunk_overlap,
            eff_ba,
            settings.chunk_semantic_merge_enabled,
        )
    )
    merge_embedder = None
    if (
        settings.chunk_semantic_merge_enabled
        and settings.chunk_semantic_merge_similarity == "embedding"
    ):
        from embeddings import build_embedder

        merge_embedder = build_embedder(settings)

    chunks, shas = load_chunks_with_sha256(
        None,
        md_paths=md_paths,
        boundary_aware=eff_ba,
        semantic_merge_enabled=settings.chunk_semantic_merge_enabled,
        semantic_merge_similarity=settings.chunk_semantic_merge_similarity,
        embedding_backend=merge_embedder,
        semantic_merge_threshold=settings.chunk_semantic_merge_threshold,
        semantic_merge_min_chars=settings.chunk_semantic_merge_min_chars,
        semantic_merge_max_chars=settings.chunk_semantic_merge_max_chars,
    )
    n = len(chunks)
    print("   块数:", n)
    if n == 0:
        print("ERROR: 无 chunk", file=sys.stderr)
        return 1

    print("3) 向量编码 …")
    from embeddings import build_embedder

    embedder = merge_embedder if merge_embedder is not None else build_embedder(settings)
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

    print("4) 连接 ES …")
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore

    client = elasticsearch_client(settings)
    if not client.ping():
        print("ERROR: ES ping 失败", file=sys.stderr)
        return 1

    store = EsChunkStore(client, settings.es_index, dense_dims=dim)
    store.ensure_index(recreate=args.recreate)

    print("5) bulk 写入 …")
    docs = []
    for c, emb, sha in zip(chunks, embeddings, shas):
        sp = c.source_path or ""
        oss_u = url_by_source_path.get(sp, "")
        if not oss_u:
            print("WARN: 未匹配 OSS URL，source_path=%r" % sp, file=sys.stderr)
        docs.append(
            chunk_embedding_to_source(
                c,
                emb,
                source_sha256=sha,
                source_oss_url=oss_u,
                chunk_version=settings.chunk_version,
            )
        )
    ok_n, errs = store.bulk_index_chunks(docs)
    if errs:
        print("ERROR bulk:", errs, file=sys.stderr)
        return 1
    print("   成功条数:", ok_n)

    store.refresh()
    cnt = client.count(index=settings.es_index)
    total = int(cnt["count"])
    print("6) count:", total)
    if args.recreate and total != n:
        print("ERROR: count 与本次块数不一致（全量重建时期望相等）", file=sys.stderr)
        return 1

    if args.smoke_query.strip():
        print("7) kNN 抽检:", repr(args.smoke_query.strip()))
        qv = embedder.embed_query(args.smoke_query.strip())
        k = min(settings.retrieval_k, n)
        hits = store.search_knn(qv, k=k)
        for h in hits[:3]:
            src = h.get("source") or {}
            t = (src.get("text") or "")[:120].replace("\n", " ")
            ou = src.get("source_oss_url") or ""
            print(
                "   ",
                "score=%.4f" % h["score"],
                "id=%r" % h["id"],
                "|",
                t[:80],
                "…",
                "| oss=%s" % (ou[:80] + "…" if len(ou) > 80 else ou),
            )

    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
