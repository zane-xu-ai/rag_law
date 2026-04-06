"""ingest.loaders：与 chunking 同序、带文件 SHA。"""

from __future__ import annotations

from pathlib import Path

from chunking.split import load_all_chunks
from conf.settings import get_settings, project_root
from ingest.loaders import load_chunks_with_sha256


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
