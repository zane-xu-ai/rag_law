"""向量编码层：BGE-M3 等后端，供入库与在线检索共用。"""

from __future__ import annotations

from conf.settings import Settings

from embeddings.base import EmbeddingBackend
from embeddings.types import EmbeddingVector


def build_embedder(settings: Settings) -> EmbeddingBackend:
    """根据配置构造当前唯一的稠密后端（BGE-M3）。需安装 `[embedding]` extra。"""
    from embeddings.bge_m3 import BgeM3EmbeddingBackend

    return BgeM3EmbeddingBackend(
        model_path=settings.bge_m3_path,
        batch_size=settings.embedding_batch_size,
        devices=settings.embedding_device,
    )


__all__ = [
    "EmbeddingBackend",
    "EmbeddingVector",
    "build_embedder",
]
