"""metrics_retrieval 纯函数单测。"""

from __future__ import annotations

import pytest

from metrics_retrieval import mrr_score, primary_chunk_id, recall_hit_at_k


def test_primary_chunk_id_explicit() -> None:
    row = {"gold_primary_chunk_id": "a:1", "gold_chunk_ids": ["b:2"]}
    assert primary_chunk_id(row) == "a:1"


def test_primary_chunk_id_fallback() -> None:
    row = {"gold_chunk_ids": ["x:0", "y:1"]}
    assert primary_chunk_id(row) == "x:0"


def test_primary_chunk_id_empty_raises() -> None:
    with pytest.raises(ValueError):
        primary_chunk_id({"gold_chunk_ids": []})


def test_recall_hit_at_k() -> None:
    ids = ["a", "b", "c", "d"]
    assert recall_hit_at_k(ids, ["c", "z"], k=2) is False
    assert recall_hit_at_k(ids, ["c", "z"], k=3) is True
    assert recall_hit_at_k(ids, [], k=3) is False


def test_mrr_score() -> None:
    assert mrr_score(["a", "b", "c"], "b", k_max=10) == pytest.approx(0.5)
    assert mrr_score(["a", "b"], "x", k_max=10) == 0.0
    assert mrr_score(["a", "b", "c"], "c", k_max=2) == 0.0
