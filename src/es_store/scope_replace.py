"""按 ``source_path`` 精确范围预览 / 删除 ES chunk，避免全索引误删。"""

from __future__ import annotations

from typing import Any


def _hits_total(resp: dict[str, Any]) -> int:
    t = resp.get("hits", {}).get("total", 0)
    if isinstance(t, dict):
        return int(t.get("value", 0))
    return int(t)


def preview_chunks_for_source_paths(
    client: Any,
    index: str,
    source_paths: list[str],
    *,
    sample_size: int = 30,
) -> dict[str, Any]:
    """返回当前索引中 ``source_path`` 落在给定列表内的文档统计与抽样。

    用于入库前核对「将被本轮覆盖」的现存 chunk，做到不删错、不漏删（范围与后续
    :func:`delete_chunks_by_source_paths` 一致）。
    """
    if not source_paths:
        return {
            "total": 0,
            "per_path": [],
            "samples": [],
            "source_paths_query_size": 0,
        }

    q = {"terms": {"source_path": source_paths}}
    total_body = client.search(
        index=index,
        size=0,
        track_total_hits=True,
        query=q,
    )
    total = _hits_total(total_body)

    agg_body = client.search(
        index=index,
        size=0,
        query=q,
        aggs={
            "per_path": {
                "terms": {
                    "field": "source_path",
                    "size": max(10, len(source_paths) + 5),
                },
                "aggs": {
                    "max_chunk_index": {"max": {"field": "chunk_index"}},
                },
            }
        },
    )
    buckets = (
        agg_body.get("aggregations", {})
        .get("per_path", {})
        .get("buckets", [])
    )
    per_path: list[dict[str, Any]] = []
    for b in buckets:
        per_path.append(
            {
                "source_path": b.get("key"),
                "doc_count": b.get("doc_count", 0),
                "max_chunk_index": int(
                    b.get("max_chunk_index", {}).get("value") or -1
                ),
            }
        )

    samples_body = client.search(
        index=index,
        size=sample_size,
        query=q,
        sort=[{"source_path": "asc"}, {"chunk_index": "asc"}],
        _source=[
            "source_path",
            "source_file",
            "chunk_index",
            "chunk_version",
            "text",
        ],
    )
    samples: list[dict[str, Any]] = []
    for h in samples_body.get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        samples.append(
            {
                "_id": h.get("_id"),
                "source_path": src.get("source_path"),
                "source_file": src.get("source_file"),
                "chunk_index": src.get("chunk_index"),
                "chunk_version": src.get("chunk_version"),
                "text_preview": ((src.get("text") or "")[:80] + "…")
                if src.get("text")
                else "",
            }
        )

    return {
        "total": total,
        "per_path": sorted(per_path, key=lambda x: x["source_path"] or ""),
        "samples": samples,
        "source_paths_query_size": len(source_paths),
    }


def delete_chunks_by_source_paths(
    client: Any,
    index: str,
    source_paths: list[str],
) -> dict[str, Any]:
    """删除 ``source_path`` 属于给定列表的全部 chunk（与预览查询同范围）。"""
    if not source_paths:
        return {"deleted": 0}
    return client.delete_by_query(
        index=index,
        query={"terms": {"source_path": source_paths}},
        refresh=True,
        conflicts="proceed",
    )


def verify_no_chunks_for_source_paths(
    client: Any,
    index: str,
    source_paths: list[str],
) -> int:
    """删除后校验：上述范围内文档数应为 0。返回当前命中数。"""
    if not source_paths:
        return 0
    body = client.search(
        index=index,
        size=0,
        track_total_hits=True,
        query={"terms": {"source_path": source_paths}},
    )
    return _hits_total(body)
