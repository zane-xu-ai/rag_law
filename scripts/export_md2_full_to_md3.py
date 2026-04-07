#!/usr/bin/env python3
"""将 `data/md2/<目录>/full.md` 复制到 `data/md3/<法规名>.md`。

目录名形如 `宪法.pdf-<uuid>`，输出文件名为 `宪法.md`。

项目根执行::

    uv run python scripts/export_md2_full_to_md3.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def md_name_from_md2_dir(dirname: str) -> str | None:
    if ".pdf-" not in dirname:
        return None
    return dirname.split(".pdf-", 1)[0] + ".md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="汇总 md2 子目录中的 full.md 到 data/md3/"
    )
    parser.add_argument(
        "--md2",
        type=Path,
        default=_ROOT / "data" / "md2",
        help="源目录（默认 data/md2）",
    )
    parser.add_argument(
        "--md3",
        type=Path,
        default=_ROOT / "data" / "md3",
        help="目标目录（默认 data/md3）",
    )
    args = parser.parse_args()

    md2: Path = args.md2.resolve()
    md3: Path = args.md3.resolve()

    if not md2.is_dir():
        print(f"错误：不存在或不是目录: {md2}", file=sys.stderr)
        return 1

    md3.mkdir(parents=True, exist_ok=True)

    first_source_for_name: dict[str, Path] = {}
    copied = 0
    skipped = 0

    for sub in sorted(md2.iterdir()):
        if not sub.is_dir():
            continue
        full_md = sub / "full.md"
        if not full_md.is_file():
            continue

        out_name = md_name_from_md2_dir(sub.name)
        if out_name is None:
            print(
                f"警告：跳过（目录名不含 `.pdf-`）: {sub.relative_to(_ROOT)}",
                file=sys.stderr,
            )
            skipped += 1
            continue

        dest = md3 / out_name
        if out_name in first_source_for_name:
            prev = first_source_for_name[out_name]
            if prev != sub:
                print(
                    f"警告：多个源目录映射到同一目标 {out_name!r}: "
                    f"{prev.relative_to(_ROOT)} 与 {sub.relative_to(_ROOT)}",
                    file=sys.stderr,
                )
        else:
            first_source_for_name[out_name] = sub

        shutil.copy2(full_md, dest)
        copied += 1
        print(f"{full_md.relative_to(_ROOT)} -> {dest.relative_to(_ROOT)}")

    print(f"完成：复制 {copied} 个文件到 {md3.relative_to(_ROOT)}；跳过 {skipped} 个目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
