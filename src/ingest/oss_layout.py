"""OSS 对象 key 与本地下载路径、`source_path` 的对应关系（与 `scripts/ingest_oss_md_to_es.py` 一致）。"""

from __future__ import annotations

from pathlib import Path


def local_md_filename_for_oss_key(object_key: str) -> str:
    """将 OSS object key 转为本地文件名：``/`` → ``__``，保证无目录冲突。"""
    k = object_key.strip("/").replace("/", "__")
    if not k.lower().endswith(".md"):
        k = f"{k}.md"
    return k


def iter_oss_md_ingest_plan(
    project_root: Path,
    download_dir: Path,
    oss_object_keys: list[str],
) -> list[tuple[str, Path, str]]:
    """对若干 OSS key 计算与入库一致的 ``(source_path, local_path, oss_key)`` 列表。

    ``source_path`` 为相对 ``project_root`` 的 posix 路径（与 ``TextChunk.source_path`` 一致）。
    """
    root = project_root.resolve()
    dd = download_dir.expanduser()
    if not dd.is_absolute():
        dd = (root / dd).resolve()
    else:
        dd = dd.resolve()

    out: list[tuple[str, Path, str]] = []
    for key in oss_object_keys:
        local = dd / local_md_filename_for_oss_key(key)
        try:
            rel = local.resolve().relative_to(root)
            sp = rel.as_posix()
        except ValueError:
            sp = str(local.resolve())
        out.append((sp, local, key))
    return out
