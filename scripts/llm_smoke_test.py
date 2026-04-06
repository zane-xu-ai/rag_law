#!/usr/bin/env python3
"""LLM 连通性冒烟：读取 `MODEL_*`，调用 OpenAI 兼容 `chat.completions` 最小请求。

项目根执行::

    uv sync --extra llm
    uv run python scripts/llm_smoke_test.py
    uv run python scripts/llm_smoke_test.py --dry-run

需 `.env` 中 `MODEL_API_KEY` / `MODEL_BASE_URL` / `MODEL_NAME`；会产生少量计费（`max_tokens` 已压到 8）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def _redact_api_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return "%s...%s" % (key[:4], key[-4:])


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM OpenAI 兼容接口连通性冒烟")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印配置（脱敏），不发起 HTTP",
    )
    args = parser.parse_args()

    from conf.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    print("MODEL_BASE_URL:", settings.model_base_url)
    print("MODEL_NAME:", settings.model_name)
    print("MODEL_API_KEY:", _redact_api_key(settings.model_api_key))

    if args.dry_run:
        print("--dry-run：跳过 API 调用")
        return 0

    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        print(
            "ERROR: 未安装 openai。请执行: uv sync --extra llm",
            file=sys.stderr,
        )
        return 1

    client = OpenAI(
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
    )
    try:
        resp = client.chat.completions.create(
            model=settings.model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
        )
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e), file=sys.stderr)
        return 1

    cid = getattr(resp, "id", None) or (resp.get("id") if isinstance(resp, dict) else None)
    choice = resp.choices[0] if resp.choices else None
    content = ""
    if choice and choice.message and choice.message.content:
        content = choice.message.content
    print("completion id:", cid)
    print("reply:", repr(content))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
