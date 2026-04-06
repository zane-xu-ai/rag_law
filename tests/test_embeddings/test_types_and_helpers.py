"""`embeddings.types` 与 `bge_m3` 辅助函数覆盖。"""

from __future__ import annotations

import pytest

from embeddings.bge_m3 import _to_numpy_2d
from embeddings.types import EmbeddingVector


def test_embedding_vector_as_dict() -> None:
    v = EmbeddingVector(dense=[0.1, 0.2], sparse=None)
    assert v.as_dict() == {"dense": [0.1, 0.2], "sparse": None}


class _FakeTensor:
    """模拟 torch.Tensor：走 detach → cpu → numpy 分支。"""

    def detach(self) -> _FakeTensor:
        return self

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self):
        import numpy as np

        return np.array([[1.0, 2.0, 3.0]], dtype=np.float64)


def test_to_numpy_2d_torch_like() -> None:
    arr = _to_numpy_2d(_FakeTensor())
    assert arr.shape == (1, 3)


def test_to_numpy_2d_invalid_ndim() -> None:
    import numpy as np

    bad = np.zeros((1, 2, 3))
    with pytest.raises(ValueError, match="ndim"):
        _to_numpy_2d(bad)

