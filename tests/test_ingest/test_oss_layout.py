"""ingest.oss_layout"""

from __future__ import annotations

from pathlib import Path

from ingest.oss_layout import iter_oss_md_ingest_plan, local_md_filename_for_oss_key


def test_local_md_filename_for_oss_key() -> None:
    assert local_md_filename_for_oss_key("md3/a/b.md") == "md3__a__b.md"
    assert local_md_filename_for_oss_key("x").endswith(".md")


def test_iter_oss_md_ingest_plan_relative(tmp_path: Path) -> None:
    root = tmp_path
    dd = root / "data" / "md_minerU"
    plan = iter_oss_md_ingest_plan(root, dd, ["md3/foo.md"])
    assert len(plan) == 1
    sp, local, key = plan[0]
    assert key == "md3/foo.md"
    assert local == dd / "md3__foo.md"
    assert sp == "data/md_minerU/md3__foo.md"
