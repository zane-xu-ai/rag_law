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


def test_verify_no_chunks_for_source_paths_empty() -> None:
    client = MagicMock()
    assert verify_no_chunks_for_source_paths(client, "i", []) == 0
    client.search.assert_not_called()


def test_preview_chunks_for_source_paths_hits_total_int() -> None:
    """_hits_total 分支：total 为整数（ES 7 风格）。"""
    client = MagicMock()

    def search_side_effect(**kwargs):
        if "sort" in kwargs:
            return {"hits": {"hits": []}}
        if "aggs" in kwargs:
            return {"aggregations": {"per_path": {"buckets": []}}}
        if kwargs.get("track_total_hits"):
            return {"hits": {"total": 7}}
        raise AssertionError(kwargs)

    client.search.side_effect = search_side_effect
    out = preview_chunks_for_source_paths(client, "idx", ["p1"], sample_size=5)
    assert out["total"] == 7


def test_preview_chunks_for_source_paths_full() -> None:
    client = MagicMock()

    def search_side_effect(**kwargs):
        if "sort" in kwargs:
            assert kwargs["_source"] == [
                "source_path",
                "source_file",
                "chunk_index",
                "chunk_version",
                "text",
            ]
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "a.md:0",
                            "_source": {
                                "source_path": "data/a.md",
                                "source_file": "a.md",
                                "chunk_index": 0,
                                "chunk_version": "1.0",
                                "text": "x" * 100,
                            },
                        },
                        {
                            "_id": "b.md:1",
                            "_source": {
                                "source_path": "data/b.md",
                                "source_file": "b.md",
                                "chunk_index": 1,
                                "chunk_version": None,
                                "text": "",
                            },
                        },
                    ]
                }
            }
        if "aggs" in kwargs:
            return {
                "aggregations": {
                    "per_path": {
                        "buckets": [
                            {
                                "key": "data/b.md",
                                "doc_count": 2,
                                "max_chunk_index": {"value": 9.0},
                            },
                            {
                                "key": "data/a.md",
                                "doc_count": 1,
                                "max_chunk_index": {"value": None},
                            },
                        ]
                    }
                }
            }
        if kwargs.get("track_total_hits"):
            return {"hits": {"total": {"value": 3}}}
        raise AssertionError("unexpected search kwargs: %r" % (kwargs,))

    client.search.side_effect = search_side_effect
    out = preview_chunks_for_source_paths(client, "my_index", ["data/a.md"], sample_size=30)
    assert out["total"] == 3
    assert out["source_paths_query_size"] == 1
    assert [p["source_path"] for p in out["per_path"]] == ["data/a.md", "data/b.md"]
    assert out["per_path"][0]["max_chunk_index"] == -1
    assert out["per_path"][1]["max_chunk_index"] == 9
    assert len(out["samples"]) == 2
    assert out["samples"][0]["text_preview"].endswith("…")
    assert out["samples"][1]["text_preview"] == ""
