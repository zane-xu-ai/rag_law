"""ingest.loaders：与 chunking 同序、带文件 SHA。"""

from __future__ import annotations

from pathlib import Path

from chunking.split import load_all_chunks
from conf.settings import get_settings, project_root
import pytest

from ingest.loaders import iter_chunks_for_paths_with_sha256, load_chunks_with_sha256


def test_load_chunks_with_sha256_matches_chunk_count(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.md").write_text("一二三四五六七八九十" * 10, encoding="utf-8")

    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)

    chunks_plain = load_all_chunks(
        data_dir=d,
        root=tmp_path,
        chunk_size=30,
        chunk_overlap=5,
    )
    chunks_s, shas = load_chunks_with_sha256(
        data_dir=d,
        root=tmp_path,
        chunk_size=30,
        chunk_overlap=5,
    )
    assert len(chunks_s) == len(chunks_plain)
    assert len(shas) == len(chunks_s)
    assert len(set(shas)) == 1


def test_load_chunks_with_sha256_md_paths_same_as_single_file_dir(
    tmp_path: Path, monkeypatch
) -> None:
    d = tmp_path / "data"
    d.mkdir()
    f = d / "a.md"
    f.write_text("一二三四五六七八九十" * 10, encoding="utf-8")

    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)

    by_dir, shas_dir = load_chunks_with_sha256(
        data_dir=d,
        root=tmp_path,
        chunk_size=30,
        chunk_overlap=5,
    )
    by_paths, shas_paths = load_chunks_with_sha256(
        None,
        md_paths=[f],
        root=tmp_path,
        chunk_size=30,
        chunk_overlap=5,
    )
    assert len(by_dir) == len(by_paths)
    assert shas_dir == shas_paths


def test_iter_chunks_for_paths_with_sha256_rejects_non_md(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="仅支持 .md"):
        list(iter_chunks_for_paths_with_sha256([f], root=tmp_path))


def test_iter_chunks_for_paths_with_sha256_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    with pytest.raises(FileNotFoundError):
        list(iter_chunks_for_paths_with_sha256([missing], root=tmp_path))
