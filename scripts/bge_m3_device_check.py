#!/usr/bin/env python3
"""BGE-M3 与 Mac MPS：验证 PyTorch MPS、FlagEmbedding 默认设备；可选加载本地模型并跑一次极短编码。

项目根执行::

    uv sync --extra embedding
    uv run python scripts/bge_m3_device_check.py

需完整 `.env`（含 `BGE_M3_PATH` 等）才会加载模型；仅前两步不依赖模型路径。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def main() -> int:
    import torch

    print("torch.backends.mps.is_available() =", torch.backends.mps.is_available())

    from FlagEmbedding.abc.inference.AbsEmbedder import AbsEmbedder

    print("AbsEmbedder.get_target_devices(None) =", AbsEmbedder.get_target_devices(None))

    try:
        from conf.settings import get_settings

        get_settings.cache_clear()
        settings = get_settings()
    except Exception as e:
        print("跳过模型加载（配置未就绪）:", e)
        return 0

    from embeddings import build_embedder

    emb = build_embedder(settings)
    inner = emb._model
    td = getattr(inner, "target_devices", None)
    print("BGEM3FlagModel.target_devices =", td)

    try:
        p0 = next(inner.model.parameters())
        print("encode 前 model 首层参数 device =", p0.device)
    except Exception as e:
        print("无法读取 model.parameters():", e)
        return 0

    _ = emb.embed_query("ping")
    p1 = next(inner.model.parameters())
    print("encode 后 model 首层参数 device =", p1.device)
    if str(p0.device) == "cpu" and "mps" in str(p1.device):
        print(
            "说明：首次 encode 时 FlagEmbedding 将模型迁到 target_devices；"
            "encode 前在 cpu 属正常。"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
