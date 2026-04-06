"""`es_store`：mock ES 客户端，不连真实集群。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from es_store.chunk_defaults import apply_chunk_source_defaults
from es_store.mapping import chunk_index_mappings
from es_store.store import EsChunkStore, chunk_document_id


def test_chunk_index_mappings_dims() -> None:
    m = chunk_index_mappings(128)
    assert m["properties"]["embedding"]["dims"] == 128
    assert m["properties"]["embedding"]["similarity"] == "cosine"
    assert m["properties"]["chunk_type"]["type"] == "keyword"
    assert m["properties"]["extra"]["type"] == "flattened"


def test_apply_chunk_source_defaults() -> None:
    d = apply_chunk_source_defaults(
        {
            "text": "a",
            "embedding": [1.0],
            "source_file": "f.md",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 1,
        }
    )
    assert d["chunk_type"] == "text"
    assert d["mime_type"] == "text/markdown"
    assert d["doc_type"] == "law_md"
    assert d["domain"] == "law"
    assert d["source_path"] == ""
    assert d["source_doc_id"] == ""
    assert d["source_sha256"] == ""


def test_apply_chunk_source_defaults_preserves_explicit() -> None:
    d = apply_chunk_source_defaults(
        {
            "text": "a",
            "embedding": [1.0],
            "source_file": "f.md",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 1,
            "chunk_type": "table",
            "source_doc_id": "doc-1",
        }
    )
    assert d["chunk_type"] == "table"
    assert d["source_doc_id"] == "doc-1"


def test_chunk_index_mappings_rejects_zero() -> None:
    with pytest.raises(ValueError):
        chunk_index_mappings(0)


def test_chunk_document_id() -> None:
    assert chunk_document_id("x.md", 3) == "x.md:3"


def test_ensure_index_creates_when_missing() -> None:
    client = MagicMock()
    client.indices.exists.return_value = False
    store = EsChunkStore(client, "rag_law_doc_test", dense_dims=8)
    store.ensure_index(recreate=False)
    client.indices.create.assert_called_once()
    assert client.indices.delete.called is False


def test_ensure_index_recreate_deletes_first() -> None:
    client = MagicMock()
    client.indices.exists.side_effect = [True, False]
    store = EsChunkStore(client, "rag_law_doc_test", dense_dims=8)
    store.ensure_index(recreate=True)
    client.indices.delete.assert_called_once()
    client.indices.create.assert_called_once()


def test_ensure_index_skip_when_exists() -> None:
    client = MagicMock()
    client.indices.exists.return_value = True
    store = EsChunkStore(client, "rag_law_doc_test", dense_dims=8)
    store.ensure_index(recreate=False)
    client.indices.create.assert_not_called()


def test_bulk_index_chunks_validates_embedding_len() -> None:
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=3)
    with pytest.raises(ValueError, match="embedding"):
        store.bulk_index_chunks(
            [
                {
                    "text": "a",
                    "embedding": [0.1, 0.2],
                    "source_file": "f.md",
                    "source_path": "f.md",
                    "chunk_index": 0,
                    "char_start": 0,
                    "char_end": 1,
                }
            ]
        )


def test_search_knn_validates_dims() -> None:
    client = MagicMock()
    client.search.return_value = {"hits": {"hits": []}}
    store = EsChunkStore(client, "idx", dense_dims=3)
    with pytest.raises(ValueError, match="query_vector"):
        store.search_knn([0.1, 0.2], k=1)


def test_store_properties() -> None:
    client = MagicMock()
    store = EsChunkStore(client, "my_index", dense_dims=16)
    assert store.index_name == "my_index"
    assert store.dense_dims == 16


def test_bulk_index_chunks_empty() -> None:
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=3)
    n, errs = store.bulk_index_chunks([])
    assert n == 0
    assert errs == []


def test_bulk_index_chunks_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from es_store import store as store_mod

    monkeypatch.setattr(
        store_mod,
        "bulk",
        lambda *a, **k: (2, []),
    )
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=2)
    docs = [
        {
            "text": "a",
            "embedding": [1.0, 0.0],
            "source_file": "f.md",
            "source_path": "f.md",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 1,
        },
        {
            "text": "b",
            "embedding": [0.0, 1.0],
            "source_file": "f.md",
            "source_path": "f.md",
            "chunk_index": 1,
            "char_start": 1,
            "char_end": 2,
        },
    ]
    n, errs = store.bulk_index_chunks(docs)
    assert n == 2
    assert errs == []


def test_bulk_index_chunks_applies_defaults_to_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from es_store import store as store_mod

    actions: list = []

    def _capture_bulk(_client: object, acts: list, **kwargs: object) -> tuple[int, list]:
        actions.extend(acts)
        return len(acts), []

    monkeypatch.setattr(store_mod, "bulk", _capture_bulk)
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=2)
    store.bulk_index_chunks(
        [
            {
                "text": "a",
                "embedding": [1.0, 0.0],
                "source_file": "f.md",
                "source_path": "data/f.md",
                "chunk_index": 0,
                "char_start": 0,
                "char_end": 1,
            }
        ]
    )
    assert len(actions) == 1
    src = actions[0]["_source"]
    assert src["chunk_type"] == "text"
    assert src["mime_type"] == "text/markdown"
    assert src["source_doc_id"] == ""


def test_refresh() -> None:
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=2)
    store.refresh()
    client.indices.refresh.assert_called_once_with(index="idx")


def test_search_knn_k_invalid() -> None:
    client = MagicMock()
    store = EsChunkStore(client, "idx", dense_dims=2)
    with pytest.raises(ValueError, match="k"):
        store.search_knn([1.0, 0.0], k=0)


def test_search_knn_num_candidates_clamped_to_k() -> None:
    client = MagicMock()
    client.search.return_value = {"hits": {"hits": []}}
    store = EsChunkStore(client, "idx", dense_dims=2)
    store.search_knn([1.0, 0.0], k=10, num_candidates=3)
    call_kw = client.search.call_args[1]
    assert call_kw["knn"]["num_candidates"] == 10


def test_search_knn_parses_hits() -> None:
    client = MagicMock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "a.md:0",
                    "_score": 0.9,
                    "_source": {"text": "hi"},
                }
            ]
        }
    }
    store = EsChunkStore(client, "idx", dense_dims=2)
    hits = store.search_knn([1.0, 0.0], k=5)
    assert len(hits) == 1
    assert hits[0]["id"] == "a.md:0"
    assert hits[0]["score"] == 0.9
    assert hits[0]["source"]["text"] == "hi"


def test_search_alias_delegates_to_knn() -> None:
    client = MagicMock()
    client.search.return_value = {"hits": {"hits": []}}
    store = EsChunkStore(client, "idx", dense_dims=2)
    store.search([0.0, 1.0], k=3)
    client.search.assert_called_once()
