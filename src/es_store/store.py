"""chunk 索引：建索引、bulk 写入、kNN 检索。"""

from __future__ import annotations

from typing import Any

from elasticsearch.helpers import bulk


def chunk_document_id(source_file: str, chunk_index: int) -> str:
    """稳定文档 _id：便于幂等 bulk。"""
    return "%s:%s" % (source_file, chunk_index)


class EsChunkStore:
    """封装 `ES_INDEX` 对应的 chunk 索引操作。"""

    def __init__(
        self,
        client: Any,
        index_name: str,
        *,
        dense_dims: int,
    ) -> None:
        self._client = client
        self._index_name = index_name
        self._dense_dims = dense_dims

    @property
    def index_name(self) -> str:
        return self._index_name

    @property
    def dense_dims(self) -> int:
        return self._dense_dims

    def ensure_index(self, *, recreate: bool = False) -> None:
        """若索引不存在则创建；`recreate=True` 时先删后建。"""
        from es_store.mapping import chunk_index_mappings

        if recreate and self._client.indices.exists(index=self._index_name):
            self._client.indices.delete(index=self._index_name)
        if self._client.indices.exists(index=self._index_name):
            return
        self._client.indices.create(
            index=self._index_name,
            mappings=chunk_index_mappings(self._dense_dims),
        )

    def bulk_index_chunks(self, documents: list[dict[str, Any]]) -> tuple[int, list[Any]]:
        """批量索引 chunk 文档。每条须含 `text`、`embedding`、元数据字段；`embedding` 长度须等于 `dense_dims`。

        返回 `(成功条数, bulk 错误列表)`。
        """
        actions = []
        for doc in documents:
            emb = doc.get("embedding")
            if emb is None or len(emb) != self._dense_dims:
                raise ValueError(
                    "embedding 须为长度 %s 的向量，得到 %s"
                    % (self._dense_dims, None if emb is None else len(emb))
                )
            sf = doc["source_file"]
            ci = int(doc["chunk_index"])
            _id = chunk_document_id(sf, ci)
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self._index_name,
                    "_id": _id,
                    "_source": doc,
                }
            )
        if not actions:
            return 0, []
        ok, errors = bulk(self._client, actions, refresh="wait_for")
        return int(ok), list(errors or [])

    def refresh(self) -> None:
        self._client.indices.refresh(index=self._index_name)

    def search_knn(
        self,
        query_vector: list[float],
        k: int,
        *,
        num_candidates: int | None = None,
    ) -> list[dict[str, Any]]:
        """对 `embedding` 做 kNN；向量须与索引 `similarity: cosine` 一致（通常已 L2 归一化）。"""
        if len(query_vector) != self._dense_dims:
            raise ValueError(
                "query_vector 维度须为 %s，得到 %s"
                % (self._dense_dims, len(query_vector))
            )
        if k < 1:
            raise ValueError("k 必须 >= 1")
        nc = num_candidates if num_candidates is not None else max(100, k * 20)
        if nc < k:
            nc = k

        resp = self._client.search(
            index=self._index_name,
            knn={
                "field": "embedding",
                "query_vector": query_vector,
                "k": k,
                "num_candidates": nc,
            },
        )
        out: list[dict[str, Any]] = []
        for hit in resp.get("hits", {}).get("hits", []):
            out.append(
                {
                    "id": hit["_id"],
                    "score": float(hit["_score"]),
                    "source": hit.get("_source") or {},
                }
            )
        return out

    def search(self, query_vector: list[float], k: int, **kwargs: Any) -> list[dict[str, Any]]:
        """与计划文档一致的别名：`search(query_vector, k)` → `search_knn`。"""
        return self.search_knn(query_vector, k, **kwargs)
