"""向量后端抽象：与 LangChain 风格 `embed_documents` / `embed_query` 对齐。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingBackend(Protocol):
    """本地或远程嵌入模型统一接口。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """对文档/段落批量编码；返回与 `texts` 等长的稠密向量列表。"""
        ...

    def embed_query(self, text: str) -> list[float]:
        """对检索查询编码（可与 `embed_documents` 使用不同前缀或长度上限）。"""
        ...

    @property
    def dense_dimension(self) -> int:
        """首次成功编码后由实现写入；供 ES `dense_vector` 的 `dims` 使用。"""
        ...

