"""`embeddings.bge_m3`：mock 模型，不加载真实 BGE-M3 / torch。"""

from __future__ import annotations

import sys

import pytest

from conf.settings import get_settings
from embeddings.bge_m3 import BgeM3EmbeddingBackend, _l2_normalize_rows, _to_numpy_2d


class _FakeTorchCuda:
    @staticmethod
    def is_available() -> bool:
        return False


class _FakeTorch:
    cuda = _FakeTorchCuda()


class _FakeBGEM3ModelDimMismatch:
    """第二次编码与第一次维度不一致，触发 `_set_dim_if_needed` 报错。"""

    def __init__(self, model_path: str, **kwargs: object) -> None:
        del model_path, kwargs

    def encode_queries(
        self,
        queries: object,
        **kwargs: object,
    ) -> dict[str, list[list[float]]]:
        del queries, kwargs
        return {"dense_vecs": [[1.0, 0.0, 0.0]]}

    def encode_corpus(
        self,
        corpus: object,
        **kwargs: object,
    ) -> dict[str, list[list[float]]]:
        del kwargs
        if isinstance(corpus, str):
            n = 1
        else:
            n = len(list(corpus))
        return {
            "dense_vecs": [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in range(n)],
        }


class _FakeBGEM3Model:
    """模拟 FlagEmbedding：query 与 corpus 分路，返回未归一化向量（嵌套 list，无需顶层 import numpy）。"""

    def __init__(self, model_path: str, **kwargs: object) -> None:
        self.model_path = model_path
        self.kwargs = kwargs

    def encode_queries(
        self,
        queries: object,
        **kwargs: object,
    ) -> dict[str, list[list[float]]]:
        del queries, kwargs
        return {"dense_vecs": [[3.0, 4.0, 0.0, 0.0]]}

    def encode_corpus(
        self,
        corpus: object,
        **kwargs: object,
    ) -> dict[str, list[list[float]]]:
        del kwargs
        if isinstance(corpus, str):
            rows = [corpus]
        else:
            rows = list(corpus)
        n = len(rows)
        mat: list[list[float]] = []
        for i in range(n):
            mat.append([float(3 * (i + 1)), float(4 * (i + 1)), 0.0, 0.0])
        return {"dense_vecs": mat}


@pytest.fixture
def fake_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())


@pytest.fixture
def fake_bge_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "embeddings.bge_m3._load_bgem3_class",
        lambda: _FakeBGEM3Model,
    )


@pytest.fixture
def backend(
    fake_torch: None,
    fake_bge_class: None,
) -> BgeM3EmbeddingBackend:
    return BgeM3EmbeddingBackend("/models/bge-m3", batch_size=2)


def test_to_numpy_2d_1d_input() -> None:
    import numpy as np

    arr = _to_numpy_2d(np.array([1.0, 2.0, 3.0]))
    assert arr.shape == (1, 3)


def test_l2_normalize_rows_unit_norm(backend: BgeM3EmbeddingBackend) -> None:
    del backend
    import numpy as np

    raw = np.array([[3.0, 4.0, 0.0, 0.0]], dtype=np.float64)
    out = _l2_normalize_rows(raw)
    n = float(np.linalg.norm(out[0]))
    assert abs(n - 1.0) < 1e-6


def test_embed_query_l2_and_dimension(
    backend: BgeM3EmbeddingBackend,
) -> None:
    v = backend.embed_query("hello")
    assert len(v) == 4
    assert abs(sum(x * x for x in v) ** 0.5 - 1.0) < 1e-5
    assert backend.dense_dimension == 4


def test_embed_documents_batches_and_alignment(
    backend: BgeM3EmbeddingBackend,
) -> None:
    texts = ["a", "b", "c", "d", "e"]
    out = backend.embed_documents(texts)
    assert len(out) == 5
    for row in out:
        assert len(row) == 4
        assert abs(sum(x * x for x in row) ** 0.5 - 1.0) < 1e-5


def test_embed_documents_empty(backend: BgeM3EmbeddingBackend) -> None:
    assert backend.embed_documents([]) == []
    with pytest.raises(RuntimeError, match="dense_dimension"):
        _ = backend.dense_dimension


def test_dense_dimension_before_encode(
    fake_torch: None,
    fake_bge_class: None,
) -> None:
    del fake_torch, fake_bge_class
    b = BgeM3EmbeddingBackend("/x", batch_size=8)
    with pytest.raises(RuntimeError, match="dense_dimension"):
        _ = b.dense_dimension


def test_batch_size_must_be_positive(
    fake_torch: None,
    fake_bge_class: None,
) -> None:
    del fake_torch, fake_bge_class
    with pytest.raises(ValueError, match="batch_size"):
        BgeM3EmbeddingBackend("/m", batch_size=0)


def test_dense_dimension_mismatch_across_encode_paths(
    fake_torch: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del fake_torch
    monkeypatch.setattr(
        "embeddings.bge_m3._load_bgem3_class",
        lambda: _FakeBGEM3ModelDimMismatch,
    )
    b = BgeM3EmbeddingBackend("/m", batch_size=8)
    b.embed_query("q")
    assert b.dense_dimension == 3
    with pytest.raises(RuntimeError, match="维度不一致"):
        b.embed_documents(["a"])


def test_build_embedder(
    monkeypatch: pytest.MonkeyPatch,
    fake_torch: None,
    fake_bge_class: None,
) -> None:
    del fake_torch, fake_bge_class
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("MODEL_BASE_URL", "https://x/v1")
    monkeypatch.setenv("MODEL_NAME", "m")
    monkeypatch.setenv("BGE_M3_PATH", "/models/bge-m3")
    get_settings.cache_clear()
    from embeddings import build_embedder

    e = build_embedder(get_settings())
    assert e.embed_query("q")[0] == pytest.approx(0.6, rel=1e-5)


@pytest.mark.integration
def test_real_bge_m3_if_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """需 `uv sync --extra embedding`、有效 `BGE_M3_PATH`，并设置 RUN_BGE_M3_INTEGRATION=1。"""
    import os

    if os.environ.get("RUN_BGE_M3_INTEGRATION") != "1":
        pytest.skip("set RUN_BGE_M3_INTEGRATION=1 to run")
    pytest.importorskip("torch")
    pytest.importorskip("FlagEmbedding")

    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("MODEL_BASE_URL", "https://x/v1")
    monkeypatch.setenv("MODEL_NAME", "m")
    path = os.environ.get("BGE_M3_PATH", "")
    if not path:
        pytest.skip("BGE_M3_PATH empty")
    from pathlib import Path

    if not Path(path).exists():
        pytest.skip("BGE_M3_PATH does not exist: %s" % path)

    get_settings.cache_clear()
    from embeddings import build_embedder

    emb = build_embedder(get_settings())
    v = emb.embed_query("测试")
    assert len(v) == emb.dense_dimension
    assert abs(sum(x * x for x in v) ** 0.5 - 1.0) < 1e-2
