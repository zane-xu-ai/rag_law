"""chunk 索引 mapping：`dense_vector`、偏移与溯源元数据（见 doc/plan/v1.0.3-es-store-plan.md §4）。"""

from __future__ import annotations

from typing import Any


def chunk_index_mappings(dims: int) -> dict[str, Any]:
    """返回 `indices.create` 的 `mappings` 参数（仅 properties）。"""
    if dims < 1:
        raise ValueError("dims 必须 >= 1")
    return {
        "properties": {
            "text": {"type": "text"},
            "embedding": {
                "type": "dense_vector",
                "dims": dims,
                "index": True,
                "similarity": "cosine",
            },
            "source_file": {"type": "keyword"},
            "source_path": {"type": "keyword", "ignore_above": 2048},
            "chunk_index": {"type": "integer"},
            "char_start": {"type": "integer"},
            "char_end": {"type": "integer"},
            "chunk_type": {"type": "keyword"},
            "mime_type": {"type": "keyword"},
            "doc_type": {"type": "keyword"},
            "domain": {"type": "keyword"},
            "source_doc_id": {"type": "keyword"},
            "source_sha256": {"type": "keyword"},
            "source_oss_url": {"type": "keyword", "ignore_above": 4096},
            "chunk_version": {"type": "keyword"},
            "page_start": {"type": "integer"},
            "page_end": {"type": "integer"},
            "extra": {"type": "flattened"},
        }
    }
