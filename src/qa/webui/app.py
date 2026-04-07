"""QA WebUI：POST `/api/qa/stream` 返回 SSE；静态页挂载于 `/`。

启动时注入 ``embedder`` / ``es_client`` / ``openai_client`` 单例（见 lifespan），避免每请求重建模型与客户端。
"""

from __future__ import annotations

import importlib.util
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from qa.streaming import format_sse_event, stream_qa_events

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _openai_available() -> bool:
    """`openai` 是否可导入；测试注入的桩模块可能无 `__spec__`，`find_spec` 会抛 `ValueError`。"""
    try:
        return importlib.util.find_spec("openai") is not None
    except (ModuleNotFoundError, ValueError):
        return "openai" in sys.modules


class QAStreamBody(BaseModel):
    """单轮问答请求；`conversation_id` 预留多轮。"""

    query: str = Field(..., min_length=1, max_length=16000)
    k: int | None = Field(default=None, ge=1, le=100)
    max_tokens: int = Field(default=2048, ge=1, le=32000)
    conversation_id: str | None = Field(default=None, max_length=128)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from conf.logging_setup import configure_logging
    from conf.settings import get_settings

    from embeddings import build_embedder
    from es_store.client import elasticsearch_client

    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings)
    app.state.settings = settings
    app.state.embedder = build_embedder(settings)
    app.state.es_client = elasticsearch_client(settings)

    if _openai_available():
        from openai import OpenAI

        app.state.openai_client = OpenAI(
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
        )
    else:
        app.state.openai_client = None
    yield


app = FastAPI(
    title="rag-law QA",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "http {} {} -> {} {:.2f}ms request_id={}",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/qa/stream")
def api_qa_stream(request: Request, body: QAStreamBody) -> StreamingResponse:
    if not _openai_available():
        raise HTTPException(
            status_code=503,
            detail="未安装 openai，请执行: uv sync --extra llm",
        )
    oai: Any = getattr(request.app.state, "openai_client", None)
    if oai is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI 客户端未初始化（启动时未安装 openai）",
        )

    def sse_gen():
        for ev in stream_qa_events(
            body.query.strip(),
            settings=request.app.state.settings,
            embedder=request.app.state.embedder,
            es_client=request.app.state.es_client,
            openai_client=oai,
            k=body.k,
            max_tokens=body.max_tokens,
            conversation_id=body.conversation_id,
        ):
            yield format_sse_event(ev)

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if _STATIC_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )
