"""chunk 索引 mapping：`dense_vector` 与 MVP §6 字段对齐。"""

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
        }
    }
