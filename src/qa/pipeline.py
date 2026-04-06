"""问答流水线：embed → ES kNN → LLM。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from conf.settings import Settings


def answer_question(
    settings: Settings,
    query: str,
    *,
    k: int | None = None,
    max_tokens: int = 2048,
) -> str:
    """对 `query` 做查询向量、kNN 检索，再调用 OpenAI 兼容 `chat.completions` 返回答案正文。

    需安装可选依赖：`embedding`（BGE-M3）、`llm`（openai），以及可连通的 Elasticsearch。
    """
    from embeddings import build_embedder
    from es_store.client import elasticsearch_client
    from es_store.store import EsChunkStore
    from openai import OpenAI

    from qa.messages import build_messages

    k_eff = settings.retrieval_k if k is None else k
    embedder = build_embedder(settings)
    qv = embedder.embed_query(query)
    client = elasticsearch_client(settings)
    store = EsChunkStore(
        client,
        settings.es_index,
        dense_dims=embedder.dense_dimension,
    )
    hits = store.search_knn(qv, k=k_eff)
    messages: list[dict[str, Any]] = build_messages(
        query,
        hits,
        max_chars_per_chunk=settings.qa_max_context_chars,
    )
    oai = OpenAI(
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
    )
    resp = oai.chat.completions.create(
        model=settings.model_name,
        messages=messages,
        max_tokens=max_tokens,
    )
    choice = resp.choices[0] if resp.choices else None
    if choice and choice.message and choice.message.content:
        return choice.message.content
    return ""
