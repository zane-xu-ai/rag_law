"""Locust：压测 QA WebUI `POST /api/qa/stream`（SSE），读满流后计一次响应时间。

运行前请先启动服务，例如：
  uv run uvicorn qa.webui.app:app --host 127.0.0.1 --port 8766

执行：
  uv run locust -f scripts/load/locust/locustfile.py --host http://127.0.0.1:8766

环境变量见 scripts/load/locust/README.md。
"""

from __future__ import annotations

import os
from typing import Any

from locust import HttpUser, LoadTestShape, between, task


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v if v else default


class QAStreamUser(HttpUser):
    """对 `/api/qa/stream` 发 POST，流式读完 SSE 再结束本次请求。"""

    wait_time = between(0.5, 3.0)

    def on_start(self) -> None:
        self._query = _env_str("LOCUST_QA_QUERY", "压测短问：请用一句话回答。")
        self._k = _env_int("LOCUST_QA_K", 5)
        self._max_tokens = _env_int("LOCUST_QA_MAX_TOKENS", 128)

    @task
    def qa_stream_sse(self) -> None:
        body: dict[str, Any] = {
            "query": self._query,
            "max_tokens": self._max_tokens,
        }
        if self._k > 0:
            body["k"] = self._k

        connect_s = _env_int("LOCUST_CONNECT_TIMEOUT_S", 10)
        read_s = _env_int("LOCUST_READ_TIMEOUT_S", 600)

        with self.client.post(
            "/api/qa/stream",
            json=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            stream=True,
            name="/api/qa/stream [SSE full stream]",
            catch_response=True,
            timeout=(connect_s, read_s),
        ) as response:
            if response.status_code != 200:
                response.failure("HTTP %s" % response.status_code)
                return
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        pass
                response.success()
            except Exception as e:
                response.failure("%s: %s" % (type(e).__name__, e))


def _maybe_define_shape() -> None:
    """仅当 `LOCUST_USE_SHAPE=1` 时注册 `StagesShape`，否则可用 Web UI 手动设并发。"""

    if os.environ.get("LOCUST_USE_SHAPE", "").strip() != "1":
        return

    class StagesShape(LoadTestShape):
        """阶梯升压：存在且被注册时，Locust 按 `tick` 调度用户数（Web UI 中的用户数会被忽略）。

        阶段：(持续秒数, 目标用户数, spawn 速率 users/s)。
        环境变量 `LOCUST_SHAPE_STAGES`：`60:2:1,120:5:2,180:10:2`
        （多段逗号分隔，每段 `时长:用户数:spawn_rate`）
        """

        def __init__(self) -> None:
            super().__init__()
            raw = os.environ.get("LOCUST_SHAPE_STAGES", "").strip()
            if raw:
                self.stages: list[tuple[int, int, float]] = []
                for part in raw.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    a, b, c = part.split(":")
                    self.stages.append((int(a), int(b), float(c)))
            else:
                self.stages = [
                    (60, 2, 1.0),
                    (120, 5, 2.0),
                    (180, 10, 2.0),
                ]

        def tick(self) -> tuple[int, float] | None:
            run_time = self.get_run_time()
            acc = 0.0
            for duration, users, spawn_rate in self.stages:
                acc += float(duration)
                if run_time < acc:
                    return users, spawn_rate
            return None

    globals()["StagesShape"] = StagesShape


_maybe_define_shape()
