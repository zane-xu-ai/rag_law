"""RAG 问答：system / user 消息拼接（无网络）。"""

from __future__ import annotations

from typing import Any

DEFAULT_SYSTEM_PROMPT = """你是中文法律领域助手。你只能根据下方用户消息中给出的「检索片段」作答，不得臆测或编造法条、判例或条文编号。

必须遵守：
- 回答中不得出现「依据片段 1」「依据片段 2」或「来源文件名 + 块序号」这类引用方式。请改为法律依据表达，例如「根据《xx法》（第xx条）」；若无法确定具体条款，写作「根据《xx法》相关规定」。
- 若检索片段与问题无关、或无法从中推出结论，须明确说明，例如「根据当前检索到的材料，无法确定……」或「所提供的片段中未包含直接依据」，并禁止编造条文。
- 本回答仅为信息检索辅助，不构成法律意见或正式法律建议。"""


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "\n…（正文已截断）"


def build_user_content(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_chars_per_chunk: int,
) -> str:
    """构造 user 消息正文：用户问题 + 带序号的检索片段。"""
    lines: list[str] = [
        "【用户问题】",
        query.strip(),
        "",
        "【检索片段】",
    ]
    if not hits:
        lines.append("（未检索到相关片段；请依据系统说明作答，明确说明无法律或条文依据。）")
    else:
        for i, hit in enumerate(hits, start=1):
            src = hit.get("source") or {}
            source_file = src.get("source_file", "(unknown)")
            chunk_index = src.get("chunk_index", "")
            body = _truncate(str(src.get("text", "")), max_chars_per_chunk)
            lines.append("[{0}] 来源: {1} 块序号: {2}".format(i, source_file, chunk_index))
            lines.append(body)
            lines.append("")
    return "\n".join(lines).rstrip()


def build_messages(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_chars_per_chunk: int = 1200,
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    """组装 OpenAI `chat.completions` 所需的 messages（system + user）。"""
    sys_text = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    user_text = build_user_content(
        query,
        hits,
        max_chars_per_chunk=max_chars_per_chunk,
    )
    return [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": user_text},
    ]
