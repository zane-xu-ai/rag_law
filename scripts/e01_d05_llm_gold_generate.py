#!/usr/bin/env python3
"""v1.1.12：读取 d05 导出目录，按块调用 LLM 生成评测金标（queries + chunk_records + manifest）。

依据 doc/plan/v1.1.12-d05-llm-gold-annotation-plan.md。

项目根执行（详见 ``--help`` 与 doc/plan/v1.1.12）::

    uv sync --extra llm
    uv run python scripts/e01_d05_llm_gold_generate.py --help
    uv run python scripts/e01_d05_llm_gold_generate.py --name-contains 婚姻法 --dry-run
    uv run python scripts/e01_d05_llm_gold_generate.py --name-contains 婚姻法 --dataset-version smoke_v1 --limit-chunks 20
    uv run python scripts/e01_d05_llm_gold_generate.py --dataset-version all_v1 --resume

需 `.env`：`MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME`；金标模型用 `GENERATE_MODEL_NAME`（未设则同 `MODEL_NAME`）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
PROMPT_VERSION = "v1.1.12-e01-1"
MAX_CHUNK_CHARS_FOR_PROMPT = 14000
FRAMEWORK_LABEL = "openai_sdk"


def _try_tqdm(iterable: Any, *, total: int | None, desc: str, unit: str) -> Any:
    try:
        from tqdm import tqdm

        return tqdm(
            iterable,
            total=total,
            desc=desc,
            unit=unit,
            file=sys.stderr,
            dynamic_ncols=True,
            mininterval=0.3,
        )
    except Exception:
        return iterable


def _split_d05_chunks(full_text: str, sep: str) -> list[str]:
    parts = full_text.split(sep)
    return [p.strip() for p in parts]


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
    """同一 chunk_id 多行时保留最后一行（失败重试后追加成功行时，以最后一次为准）。"""
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
    """已完成：最新一条无 provenance.error（含合法 0 题、empty_chunk）。"""
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


def _parse_chunk_ids(
    source_file: str, gold_chunk_ids: list[str], n_chunks_in_file: int
) -> list[int]:
    out: list[int] = []
    prefix = source_file + ":"
    for gid in gold_chunk_ids:
        if not isinstance(gid, str) or ":" not in gid:
            raise ValueError("bad gold_chunk_id: %r" % (gid,))
        if not gid.startswith(prefix):
            raise ValueError("gold_chunk_id must start with %r, got %r" % (prefix, gid))
        tail = gid[len(prefix) :]
        idx = int(tail)
        if idx < 0 or idx >= n_chunks_in_file:
            raise ValueError("chunk index out of range: %s (n_chunks=%s)" % (gid, n_chunks_in_file))
        out.append(idx)
    return out


def _validate_payload(
    data: dict[str, Any],
    *,
    source_file: str,
    n_chunks_in_file: int,
    chunk_index: int,
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


def _user_prompt(
    *,
    source_file: str,
    chunk_index: int,
    n_chunks_in_file: int,
    chunk_text: str,
) -> str:
    shown = chunk_text
    truncated = False
    if len(shown) > MAX_CHUNK_CHARS_FOR_PROMPT:
        shown = shown[: MAX_CHUNK_CHARS_FOR_PROMPT // 2] + "\n\n…（中间省略）…\n\n" + shown[-MAX_CHUNK_CHARS_FOR_PROMPT // 2 :]
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
class RunStats:
    files: int = 0
    chunks: int = 0
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


EPILOG_ZH = """
参数详解（与下方 --help 一一对应）：

  --d05-dir PATH
      d05 切块导出目录，默认 data/chunk_md/d05_heading_presplit_document_segmentation。
      须与入库评测使用的切块一致。

  --out-root PATH
      金标输出根目录，默认 data/eval/gold/rag_law_d05；其下再建 --dataset-version 子目录。

  --dataset-version NAME
      本次数据集版本子目录名（如 1.0.0、smoke_hunyin_v1）。未指定时自动生成 UTC 时间戳__v1。
      非 --resume 时：该子目录须不存在或为空，避免覆盖。
      与 --resume 联用时：在已有目录上追加写入。

  --resume
      断点续跑：读取已有 chunk_records.jsonl，同一 chunk_id 以**最后一行**为准；
      若最新记录无 provenance.error，则跳过该块（不再调 API）。
      若曾为 LLM/API 失败（行内含 error），会**重新生成**并**追加**新行（保留历史行便于审计）。
      同时加载 queries.jsonl 中已有 query 文本做去重。须与首次运行使用同一 --dataset-version。

  --name-contains SUBSTR
      只处理文件名包含子串的 .md（如 婚姻法）。与 d05 导出脚本的 --name-contains 含义一致。

  --limit-files N
      只处理排序后的前 N 个 md 文件（调试用）。

  --limit-chunks N
      本运行**最多处理** N 个「未因 --resume 跳过的」chunk（含空块、含调 API 的块）；
      用于小流量试跑。被 resume 跳过的块不计入 N。

  --temperature / --max-tokens
      传给 chat.completions 的采样与长度上限。

  --dry-run
      只遍历并打印进度，不调 API、不写文件。可与 --resume 组合以查看会跳过多少块。

  --no-raw
      不写入 raw/ 下每 chunk 的原始 API 响应 JSON。

示例：

  # 仅看婚姻法有多少块、进度样式
  uv run python scripts/e01_d05_llm_gold_generate.py --name-contains 婚姻法 --dry-run

  # 婚姻法试跑 20 个 chunk
  uv run python scripts/e01_d05_llm_gold_generate.py \\
    --name-contains 婚姻法 --dataset-version smoke_hunyin_v1 --limit-chunks 20

  # 同一数据集目录续跑（换其它 --name-contains 或去掉筛选以跑更多文件时，未完成的块会继续生成）
  uv run python scripts/e01_d05_llm_gold_generate.py --dataset-version smoke_hunyin_v1 --resume

  # 全量 d05 目录下所有 md（不设 name-contains）
  uv run python scripts/e01_d05_llm_gold_generate.py --dataset-version all_laws_v1
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="d05 切块 LLM 金标生成（v1.1.12 e01）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG_ZH,
    )
    parser.add_argument(
        "--d05-dir",
        type=Path,
        default=_ROOT / "data" / "chunk_md" / "d05_heading_presplit_document_segmentation",
        help="d05 导出目录（默认 data/chunk_md/d05_heading_presplit_document_segmentation）",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "data" / "eval" / "gold" / "rag_law_d05",
        help="金标输出根目录（默认 data/eval/gold/rag_law_d05）",
    )
    parser.add_argument(
        "--dataset-version",
        type=str,
        default=None,
        help="数据集子目录名；默认自动生成 UTC 时间戳__v1",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续跑：跳过 chunk_records 中已成功完成的块，失败块重试并追加写入",
    )
    parser.add_argument("--temperature", type=float, default=0.2, help="采样温度（默认 0.2）")
    parser.add_argument("--max-tokens", type=int, default=4096, help="模型输出 max_tokens（默认 4096）")
    parser.add_argument("--dry-run", action="store_true", help="只枚举 chunk，不调 API、不写文件")
    parser.add_argument("--no-raw", action="store_true", help="不写 raw/ 原始响应")
    parser.add_argument(
        "--name-contains",
        metavar="SUBSTR",
        default=None,
        help="只处理文件名包含该子串的 .md",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="只处理前 N 个 md（调试用）",
    )
    parser.add_argument(
        "--limit-chunks",
        type=int,
        default=None,
        help="本运行最多处理 N 个未因 resume 跳过的 chunk（调试用）",
    )
    args = parser.parse_args()

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
        sub = args.name_contains
        md_files = [p for p in md_files if sub in p.name]
        if not md_files:
            print("ERROR: --name-contains 无匹配:", repr(sub), file=sys.stderr)
            return 1
    if args.limit_files is not None:
        md_files = md_files[: max(0, args.limit_files)]
    if not md_files:
        print("ERROR: 目录下无 .md 文件:", d05_dir, file=sys.stderr)
        return 1

    ver = args.dataset_version
    if not ver:
        ver = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "__v1"
    out_dir = (args.out_root if args.out_root.is_absolute() else _ROOT / args.out_root).resolve() / ver
    cr_path = out_dir / "chunk_records.jsonl"
    q_path = out_dir / "queries.jsonl"

    resume_active = bool(args.resume) and cr_path.is_file()
    if args.resume and not cr_path.is_file():
        print(
            "WARN: 指定了 --resume 但不存在 chunk_records.jsonl，按全新运行。",
            file=sys.stderr,
        )

    if out_dir.exists() and any(out_dir.iterdir()) and not args.dry_run and not resume_active:
        print(
            "ERROR: 输出目录已存在且非空。请换 --dataset-version、清空目录，或使用 --resume：",
            out_dir,
            file=sys.stderr,
        )
        return 1

    model = settings.generate_model_name_resolved
    stats = RunStats()
    stats.files = len(md_files)

    # 预扫描 chunk 总数（用于 limit-chunks 与进度）
    file_chunks: list[tuple[Path, list[str]]] = []
    total_chunks = 0
    for md_path in md_files:
        pieces = _split_d05_chunks(md_path.read_text(encoding="utf-8"), sep)
        file_chunks.append((md_path, pieces))
        total_chunks += len(pieces)

    if args.limit_chunks is not None:
        total_chunks = min(total_chunks, max(0, args.limit_chunks))

    completed_ids: set[str] = set()
    if resume_active:
        completed_ids = _completed_chunk_ids(_load_latest_chunk_records(cr_path))

    print(
        "d05: %s | md: %s | 块(扫描): %s | 输出: %s | model: %s | resume: %s | 库内已完成块: %s"
        % (
            d05_dir,
            stats.files,
            sum(len(p[1]) for p in file_chunks),
            out_dir,
            model,
            resume_active,
            len(completed_ids),
        ),
        file=sys.stderr,
    )

    if args.dry_run:
        processed_non_skip = 0
        skipped_r = 0
        for fi, (md_path, pieces) in enumerate(file_chunks):
            n = len(pieces)
            source_file = md_path.name
            for ci in range(n):
                cid = _chunk_id(source_file, ci)
                if resume_active and cid in completed_ids:
                    skipped_r += 1
                    continue
                if args.limit_chunks is not None and processed_non_skip >= args.limit_chunks:
                    print(
                        "\n dry-run: 已达 --limit-chunks（仅计未 resume 跳过的 chunk）",
                        file=sys.stderr,
                    )
                    print("dry-run: resume 跳过 %s 块" % skipped_r, file=sys.stderr)
                    return 0
                print(
                    "\r%s  %s/%s  |  chunk %s/%s   "
                    % (md_path.name, fi + 1, len(file_chunks), ci + 1, n),
                    end="",
                    file=sys.stderr,
                )
                processed_non_skip += 1
            print(file=sys.stderr)
        print(file=sys.stderr)
        print(
            "dry-run 完成。resume 跳过 %s 块；模拟处理 %s 块。未写入文件。"
            % (skipped_r, processed_non_skip),
            file=sys.stderr,
        )
        return 0

    try:
        from openai import BadRequestError, OpenAI
    except ModuleNotFoundError:
        print("ERROR: 请安装: uv sync --extra llm", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    if not args.no_raw:
        raw_dir.mkdir(parents=True, exist_ok=True)

    q_mode = "a" if resume_active else "w"
    q_f = q_path.open(q_mode, encoding="utf-8")
    cr_f = cr_path.open(q_mode, encoding="utf-8")
    if resume_active:
        stats.seen_query_norm = _load_seen_queries_from_jsonl(q_path)

    client = OpenAI(
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
    )

    created_at = datetime.now(timezone.utc).isoformat()
    processed_chunks = 0
    stop_all = False

    for fi, (md_path, pieces) in enumerate(file_chunks):
        if stop_all:
            break
        source_file = md_path.name
        n_chunks = len(pieces)
        inner_it = range(n_chunks)
        inner_it = _try_tqdm(
            inner_it,
            total=n_chunks,
            desc="%s  %s/%s" % (md_path.name, fi + 1, len(file_chunks)),
            unit="chunk",
        )
        for ci in inner_it:
            chunk_text = pieces[ci]
            cid = _chunk_id(source_file, ci)
            if resume_active and cid in completed_ids:
                stats.skipped_resume += 1
                continue

            prov_base = {
                "source_file": source_file,
                "chunk_index": ci,
                "annotator_model": model,
                "prompt_version": PROMPT_VERSION,
                "created_at": created_at,
            }

            if not chunk_text:
                stats.chunks_zero += 1
                stats.chunks += 1
                rec = {
                    "chunk_id": cid,
                    "source_file": source_file,
                    "chunk_index": ci,
                    "n_queries": 0,
                    "skip_reason": "empty_chunk",
                    "text_sha256": _sha256_utf8(""),
                    "provenance": {**prov_base, "note": "empty after trim"},
                }
                cr_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                cr_f.flush()
                processed_chunks += 1
                continue

            stats.chunks += 1
            user_msg = _user_prompt(
                source_file=source_file,
                chunk_index=ci,
                n_chunks_in_file=n_chunks,
                chunk_text=chunk_text,
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            raw_response: dict[str, Any] = {"error": None, "content": None}
            data: dict[str, Any] | None = None
            try:
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                        response_format={"type": "json_object"},
                    )
                except BadRequestError:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                    )
                choice = resp.choices[0] if resp.choices else None
                content = (choice.message.content or "").strip() if choice and choice.message else ""
                raw_response["content"] = content
                data = _parse_json_content(content)
                nq, skip_reason, items = _validate_payload(
                    data,
                    source_file=source_file,
                    n_chunks_in_file=n_chunks,
                    chunk_index=ci,
                )
            except Exception as e:
                stats.llm_errors += 1
                nq = 0
                skip_reason = "llm_error: %s" % (type(e).__name__,)
                items = []
                raw_response["error"] = str(e)

            if not args.no_raw:
                rp = raw_dir / ("%s.json" % _safe_raw_filename(cid))
                rp.write_text(
                    json.dumps(
                        {
                            "chunk_id": cid,
                            "request_messages": messages,
                            "response": raw_response,
                            "parsed": data,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            text_hash = _sha256_utf8(chunk_text)
            if nq == 0:
                stats.chunks_zero += 1
            cr_rec = {
                "chunk_id": cid,
                "source_file": source_file,
                "chunk_index": ci,
                "n_queries": nq,
                "skip_reason": skip_reason if nq == 0 else None,
                "text_sha256": text_hash,
                "provenance": prov_base,
            }
            if raw_response.get("error"):
                cr_rec["provenance"] = {**prov_base, "error": raw_response["error"]}
            cr_f.write(json.dumps(cr_rec, ensure_ascii=False) + "\n")
            cr_f.flush()

            for qi, it in enumerate(items):
                qn = _normalize_query(it["query"])
                if qn in stats.seen_query_norm:
                    stats.dedup_removed += 1
                    continue
                stats.seen_query_norm.add(qn)
                qid = _query_row_id(source_file, ci, it["query"], qi)
                row = {
                    "schema_version": QUERIES_SCHEMA_VERSION,
                    "query_id": qid,
                    "query": it["query"],
                    "gold_chunk_ids": it["gold_chunk_ids"],
                    "gold_primary_chunk_id": it.get("gold_primary_chunk_id"),
                    "reference": it.get("reference"),
                    "provenance": {
                        **prov_base,
                        "query_index_in_chunk": qi,
                    },
                }
                if it.get("rationale"):
                    row["rationale"] = it["rationale"]
                q_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                stats.queries_written += 1
            q_f.flush()

            processed_chunks += 1

            if args.limit_chunks is not None and processed_chunks >= args.limit_chunks:
                stop_all = True
                break

        if stop_all:
            break

    q_f.close()
    cr_f.close()

    files_sha = _d05_dir_hash(d05_dir)
    disk = _scan_dataset_for_manifest(cr_path, q_path)
    manifest = {
        "dataset_name": "rag_law_d05_gold",
        "dataset_version": ver,
        "queries_schema_version": QUERIES_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "created_at": created_at,
        "run_id": uuid.uuid4().hex,
        "resume": resume_active,
        "git_commit": _git_head(),
        "d05_input": {
            "path": _relative_to_root(d05_dir),
            "files_sha256_manifest": files_sha,
        },
        "llm": {
            "model": model,
            "base_url_host": _host_only(settings.model_base_url),
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        "framework": FRAMEWORK_LABEL,
        "counts": {
            "dataset": disk,
            "last_run": {
                "md_files_scoped": stats.files,
                "chunks_processed": stats.chunks,
                "queries_written": stats.queries_written,
                "chunks_with_zero_queries": stats.chunks_zero,
                "dedup_removed": stats.dedup_removed,
                "llm_errors": stats.llm_errors,
                "skipped_resume": stats.skipped_resume,
            },
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_schema_json(out_dir / "schema.json")

    readme = """# rag_law d05 LLM 金标数据集

| 字段 | 值 |
| --- | --- |
| dataset_version | %(ver)s |
| d05 目录 | %(d05)s |
| 模型 | %(model)s |
| prompt_version | %(pv)s |
| 生成时间(UTC) | %(ts)s |
| git_commit | %(git)s |

## 文件

- `manifest.json`：运行指纹与统计（含 `counts.dataset` 聚合与 `counts.last_run` 本次增量）
- `schema.json`：`queries.jsonl` 行 JSON Schema
- `queries.jsonl`：评测用 query（去重后；`--resume` 时追加）
- `chunk_records.jsonl`：每 chunk 一行（含 0 题；同一 chunk_id 可多条，以最新行为准）
- `raw/`：每 chunk API 原始响应（若未 `--no-raw`）

续跑：同一 `--dataset-version` 下使用 `scripts/e01_d05_llm_gold_generate.py --resume`。

详见 `doc/plan/v1.1.12-d05-llm-gold-annotation-plan.md`。
""" % {
        "ver": ver,
        "d05": str(d05_dir),
        "model": model,
        "pv": PROMPT_VERSION,
        "ts": created_at,
        "git": _git_head() or "(unknown)",
    }
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    print("完成。输出目录:", out_dir, file=sys.stderr)
    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
