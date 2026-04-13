#!/usr/bin/env python3
"""金标检索评测：Recall@k、MRR（与线上一致：embed_query → ES kNN）。

用法（在项目根）::

    uv run python scripts/e03_eval_retrieval_recall_mrr.py \\
        --gold data/eval/gold/rag_law_d05/smoke_hunyin_async_v1/queries.jsonl

结果写入 ``data/eval/results/<run_id>/``（见 --output-dir）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from conf.settings import Settings
from embeddings import build_embedder
from es_store.client import elasticsearch_client
from es_store.store import EsChunkStore
from metrics_retrieval import mrr_score, primary_chunk_id, recall_hit_at_k


def _load_queries(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _default_mrr_k_max(retrieval_k: int) -> int:
    return max(20, retrieval_k * 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="金标 Recall@k / MRR 评测")
    parser.add_argument(
        "--gold",
        type=Path,
        required=True,
        help="queries.jsonl 路径（含 query、gold_chunk_ids、gold_primary_chunk_id）",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="Recall@k 的 k；默认取 Settings.retrieval_k（RETRIEVAL_K）",
    )
    parser.add_argument(
        "--mrr-k-max",
        type=int,
        default=None,
        help="MRR 截断深度；默认 max(20, k×2)，与 v1.1.11 一致",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅评测前 N 条（调试用）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录；默认 data/eval/results/<dataset>_<utc_ts>/",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="结果子目录名；默认由金标父目录名 + UTC 时间戳组成",
    )
    args = parser.parse_args()

    settings = Settings()
    k = args.k if args.k is not None else settings.retrieval_k
    mrr_k_max = args.mrr_k_max if args.mrr_k_max is not None else _default_mrr_k_max(k)
    k_retrieve = max(k, mrr_k_max)

    gold_path = args.gold.resolve()
    if not gold_path.is_file():
        print("找不到金标文件: %s" % gold_path, file=sys.stderr)
        return 2

    rows = _load_queries(gold_path)
    if args.limit is not None:
        rows = rows[: args.limit]

    embedder = build_embedder(settings)
    embedder.embed_query("ping")
    dense_dims = embedder.dense_dimension

    client = elasticsearch_client(settings)
    store = EsChunkStore(
        client,
        settings.es_index,
        dense_dims=dense_dims,
    )

    recall_hits = 0
    mrr_sum = 0.0
    n_used = 0
    n_skipped = 0
    per_query: list[dict] = []

    for row in rows:
        gold_ids = row.get("gold_chunk_ids") or []
        if not gold_ids:
            n_skipped += 1
            continue
        try:
            prim = primary_chunk_id(row)
        except ValueError:
            n_skipped += 1
            continue

        qtext = (row.get("query") or "").strip()
        if not qtext:
            n_skipped += 1
            continue

        qv = embedder.embed_query(qtext)
        hits = store.search_knn(qv, k_retrieve)
        rank_ids = [h["id"] for h in hits]

        r_hit = recall_hit_at_k(rank_ids, [str(x) for x in gold_ids], k)
        m = mrr_score(rank_ids, prim, mrr_k_max)

        recall_hits += 1 if r_hit else 0
        mrr_sum += m
        n_used += 1

        per_query.append(
            {
                "query_id": row.get("query_id"),
                "recall_hit": r_hit,
                "mrr": m,
                "primary_rank": next(
                    (i for i, rid in enumerate(rank_ids[:mrr_k_max], start=1) if rid == prim),
                    None,
                ),
            }
        )

    recall_at_k = recall_hits / n_used if n_used else 0.0
    mrr_mean = mrr_sum / n_used if n_used else 0.0

    parent_name = gold_path.parent.name
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or "%s_%s" % (parent_name, ts)
    out_root = _PROJECT_ROOT / "data" / "eval" / "results"
    out_dir = args.output_dir if args.output_dir is not None else out_root / run_id
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    env_fingerprint = {
        "es_index": settings.es_index,
        "es_host": settings.es_host,
        "es_port": settings.es_port,
        "chunk_version": settings.chunk_version or None,
        "retrieval_k_config": settings.retrieval_k,
        "bge_m3_path": settings.bge_m3_path,
        "embedding_batch_size": settings.embedding_batch_size,
        "embedding_device": settings.embedding_device,
    }

    try:
        gold_rel = str(gold_path.relative_to(_PROJECT_ROOT))
    except ValueError:
        gold_rel = str(gold_path)

    payload = {
        "schema_version": "1.0.0",
        "kind": "retrieval_recall_mrr",
        "run_at_utc": ts,
        "gold_queries_path": gold_rel,
        "metrics": {
            "recall_at_k": recall_at_k,
            "mrr": mrr_mean,
            "k": k,
            "mrr_k_max": mrr_k_max,
            "k_retrieve_es": k_retrieve,
            "n_queries_evaluated": n_used,
            "n_queries_skipped": n_skipped,
        },
        "environment": env_fingerprint,
    }

    metrics_path = out_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    per_path = out_dir / "per_query.jsonl"
    with per_path.open("w", encoding="utf-8") as f:
        for line in per_query:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    readme = out_dir / "README.md"
    readme.write_text(
        """# 检索评测结果（Recall@k / MRR）

- **metrics.json**：汇总指标与环境指纹。
- **per_query.jsonl**：逐条 recall 是否命中、MRR 得分、主块位次（若截断内出现）。

定义见仓库内 `doc/plan/v1.1.11-rag-evaluation-plan.md` 第 3～4 节。
""",
        encoding="utf-8",
    )

    print(
        "Recall@%s=%.6f  MRR(k_max=%s)=%.6f  n=%s  skipped=%s  -> %s"
        % (k, recall_at_k, mrr_k_max, mrr_mean, n_used, n_skipped, metrics_path)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
