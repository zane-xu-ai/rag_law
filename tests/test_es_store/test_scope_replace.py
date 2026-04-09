"""es_store.scope_replace"""

from __future__ import annotations

from unittest.mock import MagicMock

from es_store.scope_replace import (
    delete_chunks_by_source_paths,
    preview_chunks_for_source_paths,
    verify_no_chunks_for_source_paths,
)


def test_preview_chunks_for_source_paths_empty() -> None:
    out = preview_chunks_for_source_paths(MagicMock(), "i", [])
    assert out["total"] == 0
    assert out["per_path"] == []


def test_delete_chunks_by_source_paths_empty() -> None:
    client = MagicMock()
    out = delete_chunks_by_source_paths(client, "idx", [])
    assert out["deleted"] == 0
    client.delete_by_query.assert_not_called()


def test_delete_chunks_by_source_paths_calls_query() -> None:
    client = MagicMock()
    client.delete_by_query.return_value = {"deleted": 2}
    out = delete_chunks_by_source_paths(client, "my", ["data/a.md"])
    assert out["deleted"] == 2
    kw = client.delete_by_query.call_args.kwargs
    assert kw["index"] == "my"
    assert kw["query"] == {"terms": {"source_path": ["data/a.md"]}}


def test_verify_no_chunks_for_source_paths() -> None:
    client = MagicMock()
    client.search.return_value = {"hits": {"total": {"value": 0}}}
    assert verify_no_chunks_for_source_paths(client, "i", ["x"]) == 0
