#!/usr/bin/env python3
"""单条问题 RAG 问答：embed → ES kNN → system/user 提示 → OpenAI 兼容 chat.completions。

项目根执行::

    uv sync --extra embedding --extra llm
    uv run python scripts/rag_qa.py "你的法律问题"
    uv run python scripts/rag_qa.py "问题" --dry-run
    uv run python scripts/rag_qa.py "问题" --k 3

需 `.env` 中 `MODEL_*`、`ES_*`、`BGE_M3_PATH`；`--dry-run` 仍会访问 ES 与本地向量模型，仅跳过 LLM。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 法律问答（检索 + LLM）")
    parser.add_argument("query", help="用户问题")
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="检索条数，默认使用环境变量 RETRIEVAL_K",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不调用 LLM，仅打印 messages（JSON）",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="chat.completions 的 max_tokens（默认 2048）",
    )
    args = parser.parse_args()

    from conf.logging_setup import configure_logging
    from conf.settings import get_settings
    from embeddings import build_embedder
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore
    from qa.messages import build_messages

    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings)

    k_eff = settings.retrieval_k if args.k is None else args.k
    embedder = build_embedder(settings)
    qv = embedder.embed_query(args.query)
    client = elasticsearch_client(settings)
    store = EsChunkStore(
        client,
        settings.es_index,
        dense_dims=embedder.dense_dimension,
    )
    hits = store.search_knn(qv, k=k_eff)
    messages = build_messages(
        args.query,
        hits,
        max_chars_per_chunk=settings.qa_max_context_chars,
    )

    if args.dry_run:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return 0

    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        print(
            "ERROR: 未安装 openai。请执行: uv sync --extra llm",
            file=sys.stderr,
        )
        return 1

    oai = OpenAI(
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
    )
    try:
        resp = oai.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            max_tokens=args.max_tokens,
        )
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e), file=sys.stderr)
        return 1

    choice = resp.choices[0] if resp.choices else None
    content = ""
    if choice and choice.message and choice.message.content:
        content = choice.message.content
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
