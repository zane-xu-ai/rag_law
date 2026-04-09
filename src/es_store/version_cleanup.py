"""按 ``chunk_version`` 清理 Elasticsearch 中非当前版本的 chunk 文档。"""

from __future__ import annotations

from typing import Any


def delete_chunks_not_matching_version(
    client: Any,
    index: str,
    current_version: str,
) -> dict[str, Any]:
    """删除 ``chunk_version`` 不等于 ``current_version`` 的文档。

    含两类：显式旧版本号、以及 **缺失该字段** 或与 keyword 空串不一致的历史数据
   （``must_not`` + ``term`` 在缺失字段上不匹配当前版本，故会被删除）。

    应在 **本次新数据 bulk 完成并已 refresh** 之后调用，以免误删尚未写入的新文档。
    """
    if not current_version:
        raise ValueError("current_version 不能为空")
    return client.delete_by_query(
        index=index,
        query={
            "bool": {
                "must_not": [
                    {"term": {"chunk_version": current_version}},
                ]
            }
        },
        refresh=True,
        conflicts="proceed",
    )
