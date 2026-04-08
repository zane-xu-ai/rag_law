"""RAG 问答流式事件：分阶段计时、TTFT、总耗时；供 WebUI SSE 或单测消费。"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterator, Optional

from loguru import logger

from conf.monitor import build_qa_monitor_document, write_qa_monitor_record
from conf.token_cost import LlmCost, LlmUsage, estimate_qwen_cost_from_doc, extract_usage


def _now() -> float:
    return time.perf_counter()


def _ms(dt: float) -> float:
    return round(dt * 1000.0, 3)


def _query_fp(q: str) -> str:
    return hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]


def _provider_from_base_url(base_url: str | None) -> str:
    if not base_url:
        return "openai_compatible"
    b = str(base_url).lower()
    if "dashscope" in b or "aliyuncs" in b:
        return "dashscope"
    if "openai" in b:
        return "openai"
    return "openai_compatible"


def stream_qa_events(
    query: str,
    *,
    settings: Optional[Any] = None,
    embedder: Optional[Any] = None,
    es_client: Optional[Any] = None,
    openai_client: Optional[Any] = None,
    k: int | None = None,
    max_tokens: int = 2048,
    conversation_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """产出字典事件（由 HTTP 层序列化为 SSE）。

    计时起点 `t0`：进入本生成器后、发出 `start` 事件之前的第一时刻。
    阶段 id 对齐 doc/plan/v1.0.7-qa-webui-plan.md §4。

    若传入 ``embedder`` / ``es_client`` / ``openai_client``（如 WebUI lifespan 单例），
    对应阶段 ``elapsed_ms`` 记为 0 并带 ``cached: true``，避免每请求重建模型与客户端。
    """
    from conf.settings import get_settings

    from embeddings import build_embedder
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore
    from openai import OpenAI

    try:
        from openai import BadRequestError as _BadRequestError
    except Exception:  # pragma: no cover - 仅用于测试桩模块兼容
        _BadRequestError = Exception

    from qa.messages import build_messages

    t0 = _now()
    step_start = t0
    timings: dict[str, float] = {}

    def phase_end(phase_id: str) -> dict[str, Any]:
        nonlocal step_start
        now = _now()
        elapsed = now - step_start
        offset = now - t0
        step_start = now
        timings[phase_id] = _ms(elapsed)
        return {
            "type": "phase",
            "phase": phase_id,
            "status": "end",
            "elapsed_ms": _ms(elapsed),
            "offset_ms": _ms(offset),
        }

    def phase_cached(phase_id: str) -> dict[str, Any]:
        nonlocal step_start
        now = _now()
        offset = now - t0
        step_start = now
        timings[phase_id] = 0.0
        return {
            "type": "phase",
            "phase": phase_id,
            "status": "end",
            "elapsed_ms": 0.0,
            "offset_ms": _ms(offset),
            "cached": True,
        }

    cid = conversation_id
    yield {
        "type": "start",
        "conversation_id": cid,
        "offset_ms": 0.0,
    }

    if settings is None:
        settings = get_settings()
    yield phase_end("settings_resolve")

    if embedder is None:
        embedder = build_embedder(settings)
        yield phase_end("embedder_acquire")
    else:
        yield phase_cached("embedder_acquire")

    k_eff = settings.retrieval_k if k is None else k
    hit_count = 0
    qv = embedder.embed_query(query)
    yield phase_end("embed_query")

    if es_client is None:
        es_client = elasticsearch_client(settings)
        yield phase_end("es_client_acquire")
    else:
        yield phase_cached("es_client_acquire")

    store = EsChunkStore(
        es_client,
        settings.es_index,
        dense_dims=embedder.dense_dimension,
    )
    hits = store.search_knn(qv, k=k_eff)
    hit_count = len(hits)
    yield phase_end("es_search_knn")

    hit_summaries: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("source") or {}
        text = str(src.get("text", ""))
        preview = text[:400] + ("…" if len(text) > 400 else "")
        hit_summaries.append(
            {
                "source_file": src.get("source_file"),
                "chunk_index": src.get("chunk_index"),
                "score": h.get("score"),
                "preview": preview,
            }
        )
    yield {
        "type": "retrieval",
        "hit_count": len(hits),
        "hits": hit_summaries,
        "elapsed_ms": timings["es_search_knn"],
        "offset_ms": _ms(_now() - t0),
    }

    messages: list[dict[str, Any]] = build_messages(
        query,
        hits,
        max_chars_per_chunk=settings.qa_max_context_chars,
    )
    yield phase_end("build_messages")

    t_rag_end = _now()
    rag_prefill_ms = _ms(t_rag_end - t0)

    if openai_client is None:
        oai = OpenAI(
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
        )
        yield phase_end("llm_client_ready")
    else:
        oai = openai_client
        yield phase_cached("llm_client_ready")

    t_before_create = _now()
    try:
        stream = oai.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
    except _BadRequestError:
        # 某些 OpenAI 兼容实现不支持 stream_options；降级为无 usage 的流式。
        stream = oai.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
    t_after_create = _now()
    step_start = t_before_create
    timings["llm_stream_open"] = _ms(t_after_create - t_before_create)
    yield {
        "type": "phase",
        "phase": "llm_stream_open",
        "status": "end",
        "elapsed_ms": timings["llm_stream_open"],
        "offset_ms": _ms(t_after_create - t0),
    }
    step_start = t_after_create

    first_token_wall: float | None = None
    body_start: float | None = None
    full_text: list[str] = []
    usage: LlmUsage | None = None
    model_name_runtime: str | None = None

    try:
        for chunk in stream:
            if model_name_runtime is None:
                model_name_runtime = getattr(chunk, "model", None)
            maybe_usage = extract_usage(chunk)
            if maybe_usage is not None:
                usage = maybe_usage
            choice = chunk.choices[0] if chunk.choices else None
            delta = None
            if choice and choice.delta:
                delta = choice.delta.content
            if not delta:
                continue
            if first_token_wall is None:
                first_token_wall = _now()
                timings["llm_first_token_wait"] = _ms(first_token_wall - t_after_create)
                yield {
                    "type": "phase",
                    "phase": "llm_first_token_wait",
                    "status": "end",
                    "elapsed_ms": timings["llm_first_token_wait"],
                    "offset_ms": _ms(first_token_wall - t0),
                }
                step_start = first_token_wall
                body_start = first_token_wall
                yield {
                    "type": "metrics",
                    "ttft_ms": _ms(first_token_wall - t0),
                    "rag_prefill_ms": rag_prefill_ms,
                }
            full_text.append(delta)
            yield {"type": "delta", "content": delta}
    except Exception as e:
        yield {"type": "error", "message": "%s: %s" % (type(e).__name__, e)}
        t_end = _now()
        total_ms = _ms(t_end - t0)
        llm_total_err = _ms(t_end - t_after_create)
        ttft_err = _ms(first_token_wall - t0) if first_token_wall else None
        provider = _provider_from_base_url(getattr(settings, "model_base_url", None))
        model_for_cost = model_name_runtime or settings.model_name
        cost: LlmCost | None = None
        if settings.token_cost_enabled and usage is not None:
            cost = estimate_qwen_cost_from_doc(
                price_doc=settings.token_price_doc_resolved,
                model_name=model_for_cost,
                usage=usage,
                price_version=settings.token_price_version,
            )
        write_qa_monitor_record(
            settings,
            es_client=es_client,
            record=build_qa_monitor_document(
                settings=settings,
                query=query,
                timings=dict(timings),
                k_eff=k_eff,
                hit_count=hit_count,
                total_ms=total_ms,
                ttft_ms=ttft_err,
                rag_prefill_ms=rag_prefill_ms,
                llm_total_ms=llm_total_err,
                ok=False,
                conversation_id=cid,
                max_tokens=max_tokens,
                model_name=model_for_cost,
                provider=provider,
                usage=usage,
                cost=cost,
            ),
        )
        logger.bind(
            service="rag-law-qa",
            query_len=len(query),
            query_fp=_query_fp(query),
            retrieval_k=k_eff,
            total_ms=total_ms,
            ok=False,
        ).warning("qa_stream_done")
        yield {
            "type": "done",
            "ok": False,
            "total_ms": total_ms,
            "ttft_ms": ttft_err,
            "rag_prefill_ms": rag_prefill_ms,
            "timings": dict(timings),
            "conversation_id": cid,
        }
        return

    t_end = _now()
    if first_token_wall is None:
        timings["llm_stream_body"] = 0.0
        yield {
            "type": "phase",
            "phase": "llm_stream_body",
            "status": "end",
            "elapsed_ms": 0.0,
            "offset_ms": _ms(t_end - t0),
        }
    else:
        body_elapsed = t_end - (body_start or first_token_wall)
        timings["llm_stream_body"] = _ms(body_elapsed)
        yield {
            "type": "phase",
            "phase": "llm_stream_body",
            "status": "end",
            "elapsed_ms": timings["llm_stream_body"],
            "offset_ms": _ms(t_end - t0),
        }

    step_start = t_end
    yield phase_end("response_finalize")
    t_final = _now()

    total_ms_ok = _ms(t_final - t0)
    llm_total_ok = _ms(t_end - t_after_create)
    ttft_ok = _ms(first_token_wall - t0) if first_token_wall else None
    provider = _provider_from_base_url(getattr(settings, "model_base_url", None))
    model_for_cost = model_name_runtime or settings.model_name
    cost: LlmCost | None = None
    if settings.token_cost_enabled and usage is not None:
        cost = estimate_qwen_cost_from_doc(
            price_doc=settings.token_price_doc_resolved,
            model_name=model_for_cost,
            usage=usage,
            price_version=settings.token_price_version,
        )
    write_qa_monitor_record(
        settings,
        es_client=es_client,
        record=build_qa_monitor_document(
            settings=settings,
            query=query,
            timings=dict(timings),
            k_eff=k_eff,
            hit_count=hit_count,
            total_ms=total_ms_ok,
            ttft_ms=ttft_ok,
            rag_prefill_ms=rag_prefill_ms,
            llm_total_ms=llm_total_ok,
            ok=True,
            conversation_id=cid,
            max_tokens=max_tokens,
            model_name=model_for_cost,
            provider=provider,
            usage=usage,
            cost=cost,
        ),
    )
    logger.bind(
        service="rag-law-qa",
        query_len=len(query),
        query_fp=_query_fp(query),
        retrieval_k=k_eff,
        total_ms=total_ms_ok,
        ok=True,
    ).info("qa_stream_done")
    yield {
        "type": "done",
        "ok": True,
        "total_ms": total_ms_ok,
        "ttft_ms": _ms(first_token_wall - t0) if first_token_wall else None,
        "rag_prefill_ms": rag_prefill_ms,
        "timings": dict(timings),
        "text": "".join(full_text),
        "conversation_id": cid,
    }


def format_sse_event(obj: dict[str, Any]) -> str:
    """单条 SSE：`data: <json>\\n\\n`"""
    return "data: %s\n\n" % json.dumps(obj, ensure_ascii=False)
