"""`qa.messages`：无网络、无重依赖。"""

from __future__ import annotations

from qa.messages import DEFAULT_SYSTEM_PROMPT, build_messages, build_user_content


def test_build_messages_empty_hits_contains_sections_and_disclaimer() -> None:
    msgs = build_messages("什么是合同？", [], max_chars_per_chunk=800)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "检索片段" in msgs[1]["content"]
    assert "【用户问题】" in msgs[1]["content"]
    assert "什么是合同？" in msgs[1]["content"]
    assert "未检索到相关片段" in msgs[1]["content"]
    assert "无法律" in msgs[1]["content"] or "条文" in msgs[1]["content"]


def test_build_messages_numbered_hits_and_truncation() -> None:
    long_text = "条" * 2000
    hits = [
        {
            "id": "a.md:0",
            "score": 0.9,
            "source": {
                "source_file": "data/民法.md",
                "chunk_index": 3,
                "text": long_text,
            },
        },
        {
            "id": "b.md:1",
            "score": 0.8,
            "source": {
                "source_file": "data/宪法.md",
                "chunk_index": 0,
                "text": "短文本",
            },
        },
    ]
    msgs = build_messages("问题示例", hits, max_chars_per_chunk=100)
    user = msgs[1]["content"]
    assert "[1] 来源: data/民法.md 块序号: 3" in user
    assert "[2] 来源: data/宪法.md 块序号: 0" in user
    assert "已截断" in user
    assert "短文本" in user


def test_default_system_prompt_constraints() -> None:
    assert "检索片段" in DEFAULT_SYSTEM_PROMPT
    assert "不构成法律意见" in DEFAULT_SYSTEM_PROMPT or "法律意见" in DEFAULT_SYSTEM_PROMPT


def test_build_user_content_standalone() -> None:
    u = build_user_content(
        "q",
        [{"source": {"source_file": "x.md", "chunk_index": 1, "text": "正文"}}],
        max_chars_per_chunk=500,
    )
    assert "【用户问题】" in u
    assert "q" in u
