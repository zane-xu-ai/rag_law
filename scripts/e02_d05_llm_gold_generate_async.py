#!/usr/bin/env python3
"""v1.1.12：d05 金标异步并发生成（随机模型池 + 断点续跑 + 总体进度）。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)

QUERIES_SCHEMA_VERSION = "1.0.0"
PROMPT_VERSION = "v1.1.12-e02-async-1"
MAX_CHUNK_CHARS_FOR_PROMPT = 14000
FRAMEWORK_LABEL = "openai_sdk_async"
DEFAULT_CONCURRENCY = 30
MODEL_POOL = (
    "qwen2.5-vl-72b-instruct",
    "qwen2.5-32b-instruct",
    "qwen2.5-coder-32b-instruct",
    "qwen2.5-72b-instruct",
    "qwen2.5-vl-32b-instruct",
    "qwen2.5-math-72b-instruct",
)


def _split_d05_chunks(full_text: str, sep: str) -> list[str]:
    return [p.strip() for p in full_text.split(sep)]


def _chunk_id(source_file: str, chunk_index: int) -> str:
    return "%s:%s" % (source_file, chunk_index)


def _safe_raw_filename(chunk_id: str) -> str:
    return chunk_id.replace(":", "__").replace("/", "_")


def _sha256_utf8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _query_row_id(source_file: str, chunk_index: int, query: str, q_index: int) -> str:
    h = hashlib.sha256()
    h.update(source_file.encode("utf-8"))
    h.update(b"\n")
    h.update(str(chunk_index).encode("ascii"))
    h.update(b"\n")
    h.update(str(q_index).encode("ascii"))
    h.update(b"\n")
    h.update(query.encode("utf-8"))
    return h.hexdigest()[:16]


def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _load_latest_chunk_records(cr_path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not cr_path.is_file():
        return latest
    for line in cr_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        cid = o.get("chunk_id")
        if isinstance(cid, str):
            latest[cid] = o
    return latest


def _completed_chunk_ids(latest: dict[str, dict[str, Any]]) -> set[str]:
    done: set[str] = set()
    for cid, rec in latest.items():
        prov = rec.get("provenance") or {}
        if prov.get("error"):
            continue
        done.add(cid)
    return done


def _load_seen_queries_from_jsonl(q_path: Path) -> set[str]:
    seen: set[str] = set()
    if not q_path.is_file():
        return seen
    for line in q_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        q = o.get("query")
        if isinstance(q, str) and q.strip():
            seen.add(_normalize_query(q))
    return seen


def _scan_dataset_for_manifest(cr_path: Path, q_path: Path) -> dict[str, Any]:
    latest = _load_latest_chunk_records(cr_path)
    queries_n = 0
    if q_path.is_file():
        queries_n = sum(1 for line in q_path.read_text(encoding="utf-8").splitlines() if line.strip())
    zero_n = 0
    err_n = 0
    ok_n = 0
    for rec in latest.values():
        prov = rec.get("provenance") or {}
        if prov.get("error"):
            err_n += 1
            continue
        ok_n += 1
        if int(rec.get("n_queries") or 0) == 0:
            zero_n += 1
    return {
        "chunk_ids_unique": len(latest),
        "chunks_last_success": ok_n,
        "chunks_with_last_error": err_n,
        "chunks_with_zero_queries": zero_n,
        "queries_in_jsonl": queries_n,
    }


def _parse_json_content(raw: str) -> dict[str, Any]:
    t = (raw or "").strip()
    if not t:
        raise ValueError("empty model content")
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", t)
    if fence:
        t = fence.group(1).strip()
    return json.loads(t)


def _parse_chunk_ids(source_file: str, gold_chunk_ids: list[str], n_chunks_in_file: int) -> list[int]:
    out: list[int] = []
    prefix = source_file + ":"
    for gid in gold_chunk_ids:
        if not isinstance(gid, str) or ":" not in gid:
            raise ValueError("bad gold_chunk_id: %r" % (gid,))
        if not gid.startswith(prefix):
            raise ValueError("gold_chunk_id must start with %r, got %r" % (prefix, gid))
        idx = int(gid[len(prefix) :])
        if idx < 0 or idx >= n_chunks_in_file:
            raise ValueError("chunk index out of range: %s (n_chunks=%s)" % (gid, n_chunks_in_file))
        out.append(idx)
    return out


def _validate_payload(
    data: dict[str, Any], *, source_file: str, n_chunks_in_file: int
) -> tuple[int, str | None, list[dict[str, Any]]]:
    nq = data.get("n_queries")
    if not isinstance(nq, int) or nq < 0 or nq > 5:
        raise ValueError("n_queries must be int 0..5")
    skip = data.get("skip_reason")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be list")
    if len(items) != nq:
        raise ValueError("len(items) must equal n_queries")
    if nq == 0:
        if not skip or not isinstance(skip, str) or not str(skip).strip():
            raise ValueError("skip_reason required when n_queries=0")
        return 0, str(skip).strip(), []

    cleaned: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("item must be object")
        q = it.get("query")
        if not isinstance(q, str) or not q.strip():
            raise ValueError("item.query required")
        gids = it.get("gold_chunk_ids")
        if not isinstance(gids, list) or not gids:
            raise ValueError("gold_chunk_ids required")
        if len(gids) > 3:
            raise ValueError("at most 3 gold_chunk_ids")
        _parse_chunk_ids(source_file, [str(x) for x in gids], n_chunks_in_file)
        primary = it.get("gold_primary_chunk_id")
        if primary is not None and str(primary) not in [str(x) for x in gids]:
            raise ValueError("gold_primary_chunk_id must be in gold_chunk_ids")
        if primary is None:
            primary = str(gids[0])
        ref = it.get("reference")
        if ref is not None and not isinstance(ref, str):
            raise ValueError("reference must be string or null")
        cleaned.append(
            {
                "query": q.strip(),
                "gold_chunk_ids": [str(x) for x in gids],
                "gold_primary_chunk_id": str(primary),
                "reference": (ref.strip() if isinstance(ref, str) and ref.strip() else None),
                "rationale": (str(it["rationale"]).strip() if it.get("rationale") else None),
            }
        )
    return nq, None, cleaned


SYSTEM_PROMPT = """你是中文法律语料评测数据标注助手。你的任务是根据给定的「检索块」正文，判断是否值得为其生成用户检索问题，并输出严格 JSON（不要 Markdown 围栏以外的文字）。

规则：
1) 若该块仅为标题、极短过渡、目录性文字、无实质法条或事实，输出 n_queries=0，skip_reason 用简短英文枚举：title_only | too_short | navigational | insufficient_content（或相近说明）。
2) 若有实质内容，自判生成 1～5 条「用户可能提出的法律检索问题」；不必凑满 5 条；0～5 的上限是 5。
3) 每条问题应可被「所列 gold 块」中的文本支撑；gold_chunk_ids 使用格式「源文件名:块序号」，且最多 3 个 id；通常包含当前块；若确需相邻块请简要写在 rationale。
4) 不要虚构「第×条」法条编号；块内未出现条号时不要编造。
5) 每条可附 reference：1～3 句中文短答，仅依据所列 gold 块。
6) 输出 JSON 对象须包含：n_queries（整数）、skip_reason（无题时必填字符串，有题时可为 null）、items（数组）。items 长度必须等于 n_queries。每个 item：query, gold_chunk_ids, gold_primary_chunk_id（可选，默认取 gold_chunk_ids[0]）, reference（可选）, rationale（可选）。"""


def _user_prompt(*, source_file: str, chunk_index: int, n_chunks_in_file: int, chunk_text: str) -> str:
    shown = chunk_text
    truncated = False
    if len(shown) > MAX_CHUNK_CHARS_FOR_PROMPT:
        shown = shown[: MAX_CHUNK_CHARS_FOR_PROMPT // 2] + "\n\n…（中间省略）…\n\n" + shown[
            -MAX_CHUNK_CHARS_FOR_PROMPT // 2 :
        ]
        truncated = True
    return (
        "源文件名 source_file（与 ES chunk id 前缀一致）：%s\n"
        "当前块序号 chunk_index（从 0 起）：%s\n"
        "本文件总块数 n_chunks_in_file：%s\n"
        "正文是否截断送模：%s\n\n"
        "【块正文】\n%s\n\n"
        "请输出且仅输出一个 JSON 对象，字段见系统说明。"
        % (source_file, chunk_index, n_chunks_in_file, "是" if truncated else "否", shown)
    )


@dataclass
class ChunkTask:
    source_file: str
    chunk_index: int
    n_chunks_in_file: int
    chunk_text: str

    @property
    def chunk_id(self) -> str:
        return _chunk_id(self.source_file, self.chunk_index)


@dataclass
class ChunkResult:
    task: ChunkTask
    model: str
    provenance: dict[str, Any]
    n_queries: int
    skip_reason: str | None
    items: list[dict[str, Any]]
    raw_response: dict[str, Any]
    parsed: dict[str, Any] | None


@dataclass
class RunStats:
    files: int = 0
    chunks_processed: int = 0
    queries_written: int = 0
    chunks_zero: int = 0
    dedup_removed: int = 0
    llm_errors: int = 0
    skipped_resume: int = 0
    seen_query_norm: set[str] = field(default_factory=set)


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _d05_dir_hash(d05_dir: Path) -> str:
    h = hashlib.sha256()
    paths = sorted(d05_dir.glob("*.md"))
    for p in paths:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def _host_only(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return ""


def _relative_to_root(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(_ROOT))
    except ValueError:
        return str(p.resolve())


def _write_schema_json(path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://local/rag_law/queries.jsonl/1.0.0",
        "title": "RAG law gold query row",
        "type": "object",
        "required": ["schema_version", "query_id", "query", "gold_chunk_ids", "provenance"],
        "properties": {
            "schema_version": {"type": "string"},
            "query_id": {"type": "string"},
            "query": {"type": "string"},
            "gold_chunk_ids": {"type": "array", "items": {"type": "string"}},
            "gold_primary_chunk_id": {"type": "string"},
            "reference": {"type": "string"},
            "provenance": {"type": "object"},
        },
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")


def _progress(done: int, total: int) -> None:
    print("\r进度 %s/%s" % (done, total), end="", file=sys.stderr, flush=True)


async def _worker(
    worker_id: int,
    *,
    task_q: "asyncio.Queue[ChunkTask | None]",
    result_q: "asyncio.Queue[ChunkResult]",
    settings: Any,
    temperature: float,
    max_tokens: int,
    rng: random.Random,
) -> None:
    from openai import AsyncOpenAI, BadRequestError

    client = AsyncOpenAI(api_key=settings.model_api_key, base_url=settings.model_base_url)
    while True:
        task = await task_q.get()
        if task is None:
            task_q.task_done()
            break

        model = rng.choice(MODEL_POOL)
        prov = {
            "source_file": task.source_file,
            "chunk_index": task.chunk_index,
            "annotator_model": model,
            "prompt_version": PROMPT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "worker_id": worker_id,
        }
        raw_response: dict[str, Any] = {"error": None, "content": None}
        parsed: dict[str, Any] | None = None
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _user_prompt(
                        source_file=task.source_file,
                        chunk_index=task.chunk_index,
                        n_chunks_in_file=task.n_chunks_in_file,
                        chunk_text=task.chunk_text,
                    ),
                },
            ]
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
            except BadRequestError:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            choice = resp.choices[0] if resp.choices else None
            content = (choice.message.content or "").strip() if choice and choice.message else ""
            raw_response["content"] = content
            parsed = _parse_json_content(content)
            nq, skip_reason, items = _validate_payload(
                parsed,
                source_file=task.source_file,
                n_chunks_in_file=task.n_chunks_in_file,
            )
        except Exception as e:
            nq = 0
            skip_reason = "llm_error: %s" % (type(e).__name__,)
            items = []
            raw_response["error"] = str(e)
            prov = {**prov, "error": str(e)}

        await result_q.put(
            ChunkResult(
                task=task,
                model=model,
                provenance=prov,
                n_queries=nq,
                skip_reason=skip_reason if nq == 0 else None,
                items=items,
                raw_response=raw_response,
                parsed=parsed,
            )
        )
        task_q.task_done()


async def _writer(
    *,
    result_q: "asyncio.Queue[ChunkResult]",
    expected_results: int,
    q_f: Any,
    cr_f: Any,
    raw_dir: Path | None,
    no_raw: bool,
    stats: RunStats,
    total_scope: int,
    progress_start: int,
) -> None:
    done = progress_start
    _progress(done, total_scope)
    for _ in range(expected_results):
        res = await result_q.get()
        task = res.task
        cid = task.chunk_id

        if res.raw_response.get("error"):
            stats.llm_errors += 1
        if res.n_queries == 0:
            stats.chunks_zero += 1
        stats.chunks_processed += 1

        cr_rec = {
            "chunk_id": cid,
            "source_file": task.source_file,
            "chunk_index": task.chunk_index,
            "n_queries": res.n_queries,
            "skip_reason": res.skip_reason,
            "text_sha256": _sha256_utf8(task.chunk_text),
            "provenance": res.provenance,
        }
        cr_f.write(json.dumps(cr_rec, ensure_ascii=False) + "\n")
        cr_f.flush()

        if not no_raw and raw_dir is not None:
            rp = raw_dir / ("%s.json" % _safe_raw_filename(cid))
            rp.write_text(
                json.dumps(
                    {
                        "chunk_id": cid,
                        "response": res.raw_response,
                        "parsed": res.parsed,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        for qi, it in enumerate(res.items):
            qn = _normalize_query(it["query"])
            if qn in stats.seen_query_norm:
                stats.dedup_removed += 1
                continue
            stats.seen_query_norm.add(qn)
            qid = _query_row_id(task.source_file, task.chunk_index, it["query"], qi)
            row = {
                "schema_version": QUERIES_SCHEMA_VERSION,
                "query_id": qid,
                "query": it["query"],
                "gold_chunk_ids": it["gold_chunk_ids"],
                "gold_primary_chunk_id": it.get("gold_primary_chunk_id"),
                "reference": it.get("reference"),
                "provenance": {
                    **res.provenance,
                    "query_index_in_chunk": qi,
                },
            }
            if it.get("rationale"):
                row["rationale"] = it["rationale"]
            q_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats.queries_written += 1
        q_f.flush()

        done += 1
        _progress(done, total_scope)
        result_q.task_done()
    print(file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="d05 金标异步生成（e02）")
    p.add_argument(
        "--d05-dir",
        type=Path,
        default=_ROOT / "data" / "chunk_md" / "d05_heading_presplit_document_segmentation",
    )
    p.add_argument("--out-root", type=Path, default=_ROOT / "data" / "eval" / "gold" / "rag_law_d05")
    p.add_argument("--dataset-version", type=str, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--name-contains", metavar="SUBSTR", default=None)
    p.add_argument("--limit-files", type=int, default=None)
    p.add_argument("--limit-chunks", type=int, default=None)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-raw", action="store_true")
    return p


def main() -> int:
    args = _build_parser().parse_args()

    from chunking.md_heading_presplit import default_heading_presplit_separator
    from conf.logging_setup import configure_logging
    from conf.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings)

    d05_dir = (args.d05_dir if args.d05_dir.is_absolute() else _ROOT / args.d05_dir).resolve()
    if not d05_dir.is_dir():
        print("ERROR: d05 目录不存在:", d05_dir, file=sys.stderr)
        return 1

    sep = default_heading_presplit_separator()
    md_files = sorted(d05_dir.glob("*.md"))
    if args.name_contains:
        md_files = [p for p in md_files if args.name_contains in p.name]
        if not md_files:
            print("ERROR: --name-contains 无匹配:", repr(args.name_contains), file=sys.stderr)
            return 1
    if args.limit_files is not None:
        md_files = md_files[: max(0, args.limit_files)]
    if not md_files:
        print("ERROR: 目录下无 .md 文件", file=sys.stderr)
        return 1

    ver = args.dataset_version or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "__v1")
    out_dir = (args.out_root if args.out_root.is_absolute() else _ROOT / args.out_root).resolve() / ver
    cr_path = out_dir / "chunk_records.jsonl"
    q_path = out_dir / "queries.jsonl"
    resume_active = bool(args.resume) and cr_path.is_file()
    if args.resume and not cr_path.is_file():
        print("WARN: --resume 但不存在 chunk_records.jsonl，按全新运行。", file=sys.stderr)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.dry_run and not resume_active:
        print("ERROR: 输出目录非空；请换 --dataset-version 或使用 --resume。", file=sys.stderr)
        return 1

    all_tasks: list[ChunkTask] = []
    for md in md_files:
        pieces = _split_d05_chunks(md.read_text(encoding="utf-8"), sep)
        for idx, text in enumerate(pieces):
            all_tasks.append(
                ChunkTask(
                    source_file=md.name,
                    chunk_index=idx,
                    n_chunks_in_file=len(pieces),
                    chunk_text=text,
                )
            )

    total_scope = len(all_tasks)
    completed_ids: set[str] = set()
    if resume_active:
        completed_ids = _completed_chunk_ids(_load_latest_chunk_records(cr_path))
    pending = [t for t in all_tasks if t.chunk_id not in completed_ids]

    if args.limit_chunks is not None:
        pending = pending[: max(0, args.limit_chunks)]
    skipped_resume = total_scope - len(pending)

    print(
        "e02: md=%s, chunks=%s, pending=%s, resume_skip=%s, concurrency=%s, out=%s"
        % (len(md_files), total_scope, len(pending), skipped_resume, args.concurrency, out_dir),
        file=sys.stderr,
    )

    if args.dry_run:
        _progress(skipped_resume + len(pending), total_scope)
        print(file=sys.stderr)
        print("dry-run 完成，未写文件。", file=sys.stderr)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    if not args.no_raw:
        raw_dir.mkdir(parents=True, exist_ok=True)

    q_mode = "a" if resume_active else "w"
    q_f = q_path.open(q_mode, encoding="utf-8")
    cr_f = cr_path.open(q_mode, encoding="utf-8")
    stats = RunStats(files=len(md_files), skipped_resume=skipped_resume)
    if resume_active:
        stats.seen_query_norm = _load_seen_queries_from_jsonl(q_path)

    async def _run() -> None:
        task_q: asyncio.Queue[ChunkTask | None] = asyncio.Queue()
        result_q: asyncio.Queue[ChunkResult] = asyncio.Queue()
        rng = random.Random(args.seed)

        for t in pending:
            await task_q.put(t)
        for _ in range(max(1, args.concurrency)):
            await task_q.put(None)

        workers = [
            asyncio.create_task(
                _worker(
                    i,
                    task_q=task_q,
                    result_q=result_q,
                    settings=settings,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    rng=rng,
                )
            )
            for i in range(max(1, args.concurrency))
        ]
        writer = asyncio.create_task(
            _writer(
                result_q=result_q,
                expected_results=len(pending),
                q_f=q_f,
                cr_f=cr_f,
                raw_dir=raw_dir if not args.no_raw else None,
                no_raw=args.no_raw,
                stats=stats,
                total_scope=total_scope,
                progress_start=skipped_resume,
            )
        )
        await task_q.join()
        await asyncio.gather(*workers)
        await result_q.join()
        await writer

    try:
        asyncio.run(_run())
    finally:
        q_f.close()
        cr_f.close()

    files_sha = _d05_dir_hash(d05_dir)
    disk = _scan_dataset_for_manifest(cr_path, q_path)
    manifest = {
        "dataset_name": "rag_law_d05_gold",
        "dataset_version": ver,
        "queries_schema_version": QUERIES_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex,
        "resume": resume_active,
        "git_commit": _git_head(),
        "d05_input": {
            "path": _relative_to_root(d05_dir),
            "files_sha256_manifest": files_sha,
        },
        "llm": {
            "models_pool": list(MODEL_POOL),
            "base_url_host": _host_only(settings.model_base_url),
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "concurrency": max(1, args.concurrency),
        },
        "framework": FRAMEWORK_LABEL,
        "counts": {
            "dataset": disk,
            "last_run": {
                "md_files_scoped": stats.files,
                "chunks_processed": stats.chunks_processed,
                "queries_written": stats.queries_written,
                "chunks_with_zero_queries": stats.chunks_zero,
                "dedup_removed": stats.dedup_removed,
                "llm_errors": stats.llm_errors,
                "skipped_resume": stats.skipped_resume,
            },
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_schema_json(out_dir / "schema.json")
    (out_dir / "README.md").write_text(
        (
            "# rag_law d05 LLM 金标数据集（异步 e02）\n\n"
            "- 模型池随机调用，单写入协程避免冲突\n"
            "- 支持 --resume 断点续跑\n"
            "- 进度显示为总体进度 `done/total`\n"
        ),
        encoding="utf-8",
    )

    print("完成。输出目录:", out_dir, file=sys.stderr)
    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
