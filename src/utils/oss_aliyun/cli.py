"""CLI for Aliyun OSS CRUD.

Examples:
  uv run python -m utils.oss_aliyun.cli put --bucket my-bucket --key a.txt --file ./a.txt
  uv run python -m utils.oss_aliyun.cli get --bucket my-bucket --key a.txt --out ./tmp/a.txt
  uv run python -m utils.oss_aliyun.cli head --bucket my-bucket --key a.txt
  uv run python -m utils.oss_aliyun.cli delete --bucket my-bucket --key a.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

from utils.oss_aliyun.crud import (
    delete_object,
    get_to_file,
    head_object,
    put_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aliyun OSS CRUD CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_put = sub.add_parser("put", help="Upload local file")
    p_put.add_argument("--bucket", required=True)
    p_put.add_argument("--key", required=True)
    p_put.add_argument("--file", type=Path, required=True)

    p_get = sub.add_parser("get", help="Download object to local file")
    p_get.add_argument("--bucket", required=True)
    p_get.add_argument("--key", required=True)
    p_get.add_argument("--out", type=Path, required=True)

    p_head = sub.add_parser("head", help="Read object metadata")
    p_head.add_argument("--bucket", required=True)
    p_head.add_argument("--key", required=True)

    p_del = sub.add_parser("delete", help="Delete object")
    p_del.add_argument("--bucket", required=True)
    p_del.add_argument("--key", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "put":
        res = put_file(bucket=args.bucket, key=args.key, file_path=args.file)
        print(f"OK put: status={res.status_code} request_id={res.request_id} etag={res.etag}")
        return 0

    if args.cmd == "get":
        out = get_to_file(bucket=args.bucket, key=args.key, output=args.out)
        print(f"OK get: saved={out}")
        return 0

    if args.cmd == "head":
        meta = head_object(bucket=args.bucket, key=args.key)
        print(
            "OK head: "
            f"etag={meta.etag} content_length={meta.content_length} last_modified={meta.last_modified}"
        )
        return 0

    if args.cmd == "delete":
        res = delete_object(bucket=args.bucket, key=args.key)
        print(f"OK delete: status={res.status_code} request_id={res.request_id}")
        return 0

    raise RuntimeError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())

