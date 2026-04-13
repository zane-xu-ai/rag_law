"""金标检索指标：Recall@k、MRR（定义见 doc/plan/v1.1.11-rag-evaluation-plan.md）。"""

from __future__ import annotations

from typing import Any


def primary_chunk_id(row: dict[str, Any]) -> str:
    """主相关块 id：`gold_primary_chunk_id` 或 `gold_chunk_ids[0]`。"""
    p = row.get("gold_primary_chunk_id")
    if p is not None and str(p).strip():
        return str(p).strip()
    ids = row.get("gold_chunk_ids") or []
    if not ids:
        raise ValueError("gold_chunk_ids 为空且缺少 gold_primary_chunk_id")
    return str(ids[0]).strip()


def recall_hit_at_k(rank_ordered_ids: list[str], gold_chunk_ids: list[str], k: int) -> bool:
    """top-k 与 gold_chunk_ids 是否有交集。"""
    if k < 1:
        raise ValueError("k 必须 >= 1")
    if not gold_chunk_ids:
        return False
    top = set(rank_ordered_ids[:k])
    return any(str(g).strip() in top for g in gold_chunk_ids)


def mrr_score(rank_ordered_ids: list[str], primary_id: str, k_max: int) -> float:
    """在截断列表中找主块首次出现位置，得分 1/rank；未出现为 0。"""
    if k_max < 1:
        raise ValueError("k_max 必须 >= 1")
    pid = primary_id.strip()
    for rank, hid in enumerate(rank_ordered_ids[:k_max], start=1):
        if hid == pid:
            return 1.0 / float(rank)
    return 0.0
