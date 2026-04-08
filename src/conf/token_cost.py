"""LLM token 用量提取与价格估算（基于 doc/price_api/qwen.md）。"""

from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int | None
    cached_tokens: int | None


@dataclass(frozen=True)
class LlmCost:
    currency: str
    input_cost: float
    output_cost: float
    reasoning_cost: float | None
    total_cost: float
    price_version: str
    price_source: str


@dataclass(frozen=True)
class PriceTier:
    min_exclusive: int
    max_inclusive: int
    input_per_1m: Decimal
    output_per_1m: Decimal
    output_thinking_per_1m: Decimal | None


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def extract_usage(chunk_or_usage: Any) -> LlmUsage | None:
    """兼容 OpenAI / OpenAI-compatible usage 字段。"""
    usage = _dig(chunk_or_usage, "usage")
    if usage is None:
        usage = chunk_or_usage

    input_tokens = _to_int(_dig(usage, "prompt_tokens"))
    if input_tokens is None:
        input_tokens = _to_int(_dig(usage, "input_tokens"))
    output_tokens = _to_int(_dig(usage, "completion_tokens"))
    if output_tokens is None:
        output_tokens = _to_int(_dig(usage, "output_tokens"))
    total_tokens = _to_int(_dig(usage, "total_tokens"))

    reasoning_tokens = _to_int(_dig(usage, "reasoning_tokens"))
    if reasoning_tokens is None:
        reasoning_tokens = _to_int(_dig(usage, "completion_tokens_details", "reasoning_tokens"))
    if reasoning_tokens is None:
        reasoning_tokens = _to_int(_dig(usage, "output_tokens_details", "reasoning_tokens"))

    cached_tokens = _to_int(_dig(usage, "cached_tokens"))
    if cached_tokens is None:
        cached_tokens = _to_int(_dig(usage, "prompt_tokens_details", "cached_tokens"))
    if cached_tokens is None:
        cached_tokens = _to_int(_dig(usage, "input_tokens_details", "cached_tokens"))

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    in_t = input_tokens or 0
    out_t = output_tokens or 0
    total_t = total_tokens if total_tokens is not None else (in_t + out_t)
    return LlmUsage(
        input_tokens=in_t,
        output_tokens=out_t,
        total_tokens=total_t,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached_tokens,
    )


_RANGE_RE = re.compile(r"^\s*(\d+)K<Token≤(\d+)(K|M)\s*$")


def _parse_range_to_tokens(s: str) -> tuple[int, int] | None:
    m = _RANGE_RE.match(s)
    if not m:
        return None
    lo_k = int(m.group(1))
    hi_num = int(m.group(2))
    hi_unit = m.group(3)
    lo = lo_k * 1000
    hi = hi_num * (1_000_000 if hi_unit == "M" else 1000)
    return lo, hi


def _parse_price_num(s: str) -> Decimal | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)元", s)
    if not m:
        return None
    return Decimal(m.group(1))


@lru_cache(maxsize=64)
def _iter_cn_qwen_plus_tiers(price_doc_str: str, model_name: str) -> tuple[PriceTier, ...]:
    """从 qwen.md 的“中国内地 / 千问Plus”提取目标模型阶梯价格。"""
    price_doc = Path(price_doc_str)
    text = price_doc.read_text(encoding="utf-8")
    start = text.find("### **千问Plus**")
    if start < 0:
        return []
    scope = text[start:]
    cn = scope.split("## 全球", 1)[0]
    lines = [ln.strip() for ln in cn.splitlines() if ln.strip().startswith("|")]

    tiers: list[PriceTier] = []
    current_model = ""
    for ln in lines:
        cols = [c.strip() for c in ln.strip("|").split("|")]
        if not cols or cols[0].startswith("---") or cols[0].startswith("**"):
            continue
        first = cols[0]
        if first and not first.startswith(("0<", "128K<", "256K<", "32K<")):
            current_model = first.split(">")[0].strip()
        if current_model != model_name:
            continue

        token_range = cols[1] if first == current_model else cols[0]
        rng = _parse_range_to_tokens(token_range)
        if rng is None:
            # 无阶梯计价：直接跳过（这里优先处理阶梯模型）
            continue
        lo, hi = rng

        # qwen-plus 中国内地表列：输入、非思考输出、思考输出（有些行可能无思考列）
        if first == current_model:
            in_col = cols[2] if len(cols) > 2 else ""
            out_col = cols[3] if len(cols) > 3 else ""
            think_col = cols[4] if len(cols) > 4 else ""
        else:
            in_col = cols[1] if len(cols) > 1 else ""
            out_col = cols[2] if len(cols) > 2 else ""
            think_col = cols[3] if len(cols) > 3 else ""

        in_price = _parse_price_num(in_col)
        out_price = _parse_price_num(out_col)
        think_price = _parse_price_num(think_col)
        if in_price is None or out_price is None:
            continue
        tiers.append(
            PriceTier(
                min_exclusive=lo,
                max_inclusive=hi,
                input_per_1m=in_price,
                output_per_1m=out_price,
                output_thinking_per_1m=think_price,
            )
        )
    return tuple(tiers)


def estimate_qwen_cost_from_doc(
    *,
    price_doc: Path,
    model_name: str,
    usage: LlmUsage,
    price_version: str,
) -> LlmCost | None:
    tiers = list(_iter_cn_qwen_plus_tiers(str(price_doc), model_name=model_name))
    if not tiers:
        return None

    tier = None
    for t in tiers:
        if usage.input_tokens > t.min_exclusive and usage.input_tokens <= t.max_inclusive:
            tier = t
            break
    if tier is None:
        tier = tiers[-1]

    out_price = tier.output_per_1m
    if usage.reasoning_tokens and tier.output_thinking_per_1m is not None:
        out_price = tier.output_thinking_per_1m

    in_cost = (Decimal(usage.input_tokens) / Decimal(1_000_000)) * tier.input_per_1m
    out_cost = (Decimal(usage.output_tokens) / Decimal(1_000_000)) * out_price
    total = (in_cost + out_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return LlmCost(
        currency="CNY",
        input_cost=float(in_cost),
        output_cost=float(out_cost),
        reasoning_cost=None,
        total_cost=float(total),
        price_version=price_version,
        price_source=str(price_doc),
    )
