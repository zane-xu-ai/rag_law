from __future__ import annotations

from pathlib import Path

from conf.token_cost import LlmUsage, estimate_qwen_cost_from_doc, extract_usage


class _UsageObj:
    prompt_tokens = 1000
    completion_tokens = 200
    total_tokens = 1200

    class completion_tokens_details:
        reasoning_tokens = 50

    class prompt_tokens_details:
        cached_tokens = 10


class _ChunkObj:
    usage = _UsageObj()


def test_extract_usage_from_chunk_obj() -> None:
    usage = extract_usage(_ChunkObj())
    assert usage is not None
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 200
    assert usage.total_tokens == 1200
    assert usage.reasoning_tokens == 50
    assert usage.cached_tokens == 10


def test_estimate_qwen_cost_from_doc_qwen_plus() -> None:
    usage = LlmUsage(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        reasoning_tokens=10,
        cached_tokens=0,
    )
    doc = Path(__file__).resolve().parents[2] / "doc/price_api/qwen.md"
    cost = estimate_qwen_cost_from_doc(
        price_doc=doc,
        model_name="qwen-plus",
        usage=usage,
        price_version="qwen-md-v1",
    )
    assert cost is not None
    assert cost.currency == "CNY"
    assert cost.total_cost > 0.0
