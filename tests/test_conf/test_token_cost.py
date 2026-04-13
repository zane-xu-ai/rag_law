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


def test_extract_usage_from_dict_usage_alternate_keys() -> None:
    u = extract_usage(
        {
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "output_tokens_details": {"reasoning_tokens": 3},
                "input_tokens_details": {"cached_tokens": 4},
            }
        }
    )
    assert u is not None
    assert u.input_tokens == 10
    assert u.output_tokens == 20
    assert u.reasoning_tokens == 3
    assert u.cached_tokens == 4


def test_extract_usage_returns_none_when_empty() -> None:
    assert extract_usage({"usage": {}}) is None


def test_estimate_qwen_uses_last_tier_when_input_out_of_table() -> None:
    usage = LlmUsage(
        input_tokens=999_999_999,
        output_tokens=100,
        total_tokens=1_000_000_099,
        reasoning_tokens=None,
        cached_tokens=None,
    )
    doc = Path(__file__).resolve().parents[2] / "doc/price_api/qwen.md"
    cost = estimate_qwen_cost_from_doc(
        price_doc=doc,
        model_name="qwen-plus",
        usage=usage,
        price_version="qwen-md-v1",
    )
    assert cost is not None
    assert cost.total_cost > 0.0


def test_estimate_qwen_reasoning_switches_output_price_when_thinking_column() -> None:
    usage = LlmUsage(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        reasoning_tokens=400,
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


def test_estimate_qwen_returns_none_for_unknown_model() -> None:
    usage = LlmUsage(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        reasoning_tokens=None,
        cached_tokens=None,
    )
    doc = Path(__file__).resolve().parents[2] / "doc/price_api/qwen.md"
    assert (
        estimate_qwen_cost_from_doc(
            price_doc=doc,
            model_name="definitely-not-in-table-xyz",
            usage=usage,
            price_version="qwen-md-v1",
        )
        is None
    )
