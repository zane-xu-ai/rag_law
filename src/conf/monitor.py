"""QA 请求监控：JSONL（`logs/monitor.log`）与可选 Elasticsearch 索引。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from conf.settings import Settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def query_fingerprint(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def build_qa_monitor_document(
    *,
    settings: Settings,
    query: str,
    timings: dict[str, float],
    k_eff: int,
    hit_count: int,
    total_ms: float,
    ttft_ms: float | None,
    rag_prefill_ms: float,
    llm_total_ms: float | None,
    ok: bool,
    conversation_id: str | None,
    max_tokens: int,
) -> dict[str, Any]:
    """单条监控文档（与 v1.1.1 计划 §1.1 字段对齐）；不含用户原文。"""
    return {
        "@timestamp": utc_now_iso(),
        "service": "rag-law-qa",
        "event": "qa_request",
        "ok": ok,
        "conversation_id": conversation_id,
        "query_len": len(query),
        "query_fp": query_fingerprint(query),
        "retrieval_k": k_eff,
        "retrieval_hit_count": hit_count,
        "max_tokens": max_tokens,
        "total_ms": total_ms,
        "ttft_ms": ttft_ms,
        "rag_prefill_ms": rag_prefill_ms,
        "llm_total_ms": llm_total_ms,
        "embed_query_ms": timings.get("embed_query"),
        "es_search_knn_ms": timings.get("es_search_knn"),
        "timings": dict(timings),
    }


def write_qa_monitor_record(
    settings: Settings,
    *,
    es_client: Any | None = None,
    record: dict[str, Any],
) -> None:
    """追加 JSONL；若 `monitor_es_enabled` 且提供 `es_client` 则写入 ES。"""
    path = settings.monitor_log_file_resolved
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    if settings.monitor_es_enabled and es_client is not None:
        try:
            es_client.index(
                index=settings.monitor_es_index,
                document=record,
                refresh=False,
            )
        except Exception as e:
            logger.warning("monitor_es_index_failed: {}", e)
