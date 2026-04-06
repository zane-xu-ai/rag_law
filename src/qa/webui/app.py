"""QA WebUI：POST `/api/qa/stream` 返回 SSE；静态页挂载于 `/`。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from qa.streaming import format_sse_event, stream_qa_events

_STATIC_DIR = Path(__file__).resolve().parent / "static"


class QAStreamBody(BaseModel):
    """单轮问答请求；`conversation_id` 预留多轮。"""

    query: str = Field(..., min_length=1, max_length=16000)
    k: int | None = Field(default=None, ge=1, le=100)
    max_tokens: int = Field(default=2048, ge=1, le=32000)
    conversation_id: str | None = Field(default=None, max_length=128)


app = FastAPI(title="rag-law QA", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/qa/stream")
def api_qa_stream(body: QAStreamBody) -> StreamingResponse:
    import importlib.util

    if importlib.util.find_spec("openai") is None:
        raise HTTPException(
            status_code=503,
            detail="未安装 openai，请执行: uv sync --extra llm",
        )

    def sse_gen():
        for ev in stream_qa_events(
            body.query.strip(),
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
