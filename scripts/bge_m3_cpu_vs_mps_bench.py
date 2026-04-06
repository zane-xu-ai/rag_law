#!/usr/bin/env python3
"""BGE-M3 在 CPU 与 MPS（若可用）上的简单吞吐对比：约 10 条短句，不含模型加载时间。

项目根执行::

    uv sync --extra embedding
    uv run python scripts/bge_m3_cpu_vs_mps_bench.py

需 `.env` 中 `BGE_M3_PATH` 等完整配置。会依次加载两次模型（cpu / mps），内存占用较大。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)

# 约 10 条中文短句（法律检索风格，长度适中）
SENTENCES = [
    "中华人民共和国公民的基本权利由哪些法律保障？",
    "劳动合同解除时用人单位应当如何支付经济补偿？",
    "行政诉讼的受案范围包括哪些情形？",
    "民事诉讼法规定的举证责任分配原则是什么？",
    "刑法中关于正当防卫的成立条件有哪些？",
    "行政复议与行政诉讼的衔接关系如何理解？",
    "物权法上善意取得的构成要件是什么？",
    "消费者权益保护法规定的惩罚性赔偿适用于哪些情况？",
    "公司法中股东查阅公司会计账簿的条件是什么？",
    "知识产权侵权诉讼中如何确定赔偿数额？",
]


def _bench_one(devices: str | None) -> tuple[float, float, float]:
    """返回 (load_ms, warmup_ms, total_embed_ms)。load 含构造与 MPS 内置预热。"""
    from conf.settings import get_settings

    from embeddings.bge_m3 import BgeM3EmbeddingBackend

    get_settings.cache_clear()
    settings = get_settings()

    t0 = time.perf_counter()
    kw: dict = {}
    if devices is not None:
        kw["devices"] = devices
    emb = BgeM3EmbeddingBackend(
        settings.bge_m3_path,
        batch_size=settings.embedding_batch_size,
        **kw,
    )
    load_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    _ = emb.embed_query("ping")
    warmup_ms = (time.perf_counter() - t1) * 1000.0

    t2 = time.perf_counter()
    for s in SENTENCES:
        _ = emb.embed_query(s)
    total_ms = (time.perf_counter() - t2) * 1000.0

    del emb
    return load_ms, warmup_ms, total_ms


def main() -> int:
    import torch

    mps_ok = bool(torch.backends.mps.is_available())
    print("torch.backends.mps.is_available() =", mps_ok)
    print("句子数 =", len(SENTENCES))
    print()

    results: dict[str, tuple[float, float, float]] = {}
    results["cpu"] = _bench_one("cpu")
    print(
        "[cpu]  加载(含构造与内置预热) %.1f ms | 额外 warmup %.1f ms | 10 条 embed 合计 %.1f ms | 均 %.1f ms/条"
        % (
            results["cpu"][0],
            results["cpu"][1],
            results["cpu"][2],
            results["cpu"][2] / len(SENTENCES),
        )
    )

    if not mps_ok:
        print("\n当前环境无 MPS，跳过 mps 对比。")
        return 0

    results["mps"] = _bench_one("mps")
    print(
        "[mps]  加载(含构造与内置预热) %.1f ms | 额外 warmup %.1f ms | 10 条 embed 合计 %.1f ms | 均 %.1f ms/条"
        % (
            results["mps"][0],
            results["mps"][1],
            results["mps"][2],
            results["mps"][2] / len(SENTENCES),
        )
    )

    cpu_t = results["cpu"][2]
    mps_t = results["mps"][2]
    if mps_t > 1e-6:
        speedup = cpu_t / mps_t
        print("\n10 条合计：CPU / MPS = %.2fx（大于 1 表示 MPS 更快）" % speedup)
        if speedup >= 1.15:
            print("结论：MPS 相对 CPU 明显更快（阈值 1.15），建议在 Apple Silicon 上使用默认自动设备；代码已对 MPS 做构造后预热。")
        else:
            print("结论：本次采样下 MPS 优势未达 1.15x，仍以本机实测为准；预热逻辑仍可减少首条在线请求的迁移动耗。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
