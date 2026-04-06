"""向量载荷类型（MVP 仅用稠密；稀疏字段后续与 ES 对齐时可填）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """单次编码结果：稠密必填，稀疏可选（BGE-M3 lexical 等）。"""

    dense: list[float]
    sparse: dict[str, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"dense": self.dense, "sparse": self.sparse}

