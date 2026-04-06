"""BGE-M3（FlagEmbedding `BGEM3FlagModel`）封装：query / corpus 分路、L2 归一化。"""

from __future__ import annotations

from typing import Any, Optional


def _import_numpy():
    try:
        import numpy as np
    except ImportError as e:
        raise ImportError(
            "需要 numpy 以归一化向量。请安装：pip install numpy "
            "或 pip install -e '.[embedding]'"
        ) from e
    return np


def _to_numpy_2d(dense_vecs: Any):
    """将模型返回的 dense 转为 shape (n, dim) 的 ndarray。"""
    np = _import_numpy()
    if hasattr(dense_vecs, "detach"):
        dense_vecs = dense_vecs.detach().cpu().numpy()
    elif hasattr(dense_vecs, "cpu"):
        dense_vecs = dense_vecs.cpu().numpy()
    arr = np.asarray(dense_vecs, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    elif arr.ndim != 2:
        raise ValueError("dense_vecs 期望 1D 或 2D 数组，得到 ndim=%s" % arr.ndim)
    return arr


def _l2_normalize_rows(arr):
    np = _import_numpy()
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return arr / norms


def _load_bgem3_class():
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as e:
        raise ImportError(
            "BGE-M3 需要 FlagEmbedding 及兼容依赖（pyproject 中 [embedding] 锁定 transformers<5，避免与 FlagEmbedding 1.3.x 冲突）。"
            " 请执行：uv sync --extra embedding"
        ) from e
    return BGEM3FlagModel


class BgeM3EmbeddingBackend:
    """使用本地 `BGE_M3_PATH` 加载模型；`embed_query` 走 `encode_queries`，文档走 `encode_corpus`。"""

    def __init__(
        self,
        model_path: str,
        batch_size: int = 32,
        *,
        devices: Optional[str] = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size 必须 >= 1")
        self._batch_size = batch_size
        self._dense_dim: int | None = None

        try:
            import torch
        except ImportError as e:
            raise ImportError(
                "BGE-M3 需要 PyTorch。请安装：pip install -e '.[embedding]'"
            ) from e

        BGEM3FlagModel = _load_bgem3_class()
        use_fp16 = bool(torch.cuda.is_available())
        kw: dict[str, Any] = {
            "batch_size": batch_size,
            "use_fp16": use_fp16,
            "normalize_embeddings": False,
            "return_dense": True,
            "return_sparse": False,
            "return_colbert_vecs": False,
        }
        if devices is not None and devices.strip() != "":
            kw["devices"] = devices.strip()
        self._model = BGEM3FlagModel(model_path, **kw)
        self._maybe_warmup_mps()

    def _maybe_warmup_mps(self) -> None:
        """MPS 下 FlagEmbedding 首次 encode 才把权重迁到 GPU；启动时跑一次短 query 避免首条在线请求承担迁移耗时。"""
        td = getattr(self._model, "target_devices", None) or []
        if not any("mps" in str(d) for d in td):
            return
        _ = self.embed_query("ping")

    def _set_dim_if_needed(self, dim: int) -> None:
        if self._dense_dim is None:
            self._dense_dim = dim
        elif self._dense_dim != dim:
            raise RuntimeError(
                "dense 维度不一致：已有 %s，本次 %s" % (self._dense_dim, dim)
            )

    @property
    def dense_dimension(self) -> int:
        if self._dense_dim is None:
            raise RuntimeError(
                "dense_dimension 尚未确定：请先调用 embed_query 或 embed_documents 完成一次编码"
            )
        return self._dense_dim

    def embed_query(self, text: str) -> list[float]:
        out = self._model.encode_queries(
            text,
            batch_size=1,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense = _to_numpy_2d(out["dense_vecs"])
        normed = _l2_normalize_rows(dense)
        self._set_dim_if_needed(int(normed.shape[1]))
        return normed[0].tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        acc: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            out = self._model.encode_corpus(
                batch,
                batch_size=min(len(batch), self._batch_size),
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = _to_numpy_2d(out["dense_vecs"])
            normed = _l2_normalize_rows(dense)
            self._set_dim_if_needed(int(normed.shape[1]))
            acc.extend(normed.tolist())
        return acc
