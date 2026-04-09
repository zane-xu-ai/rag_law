"""CLI for Aliyun OSS CRUD.

Examples:
  cd <项目根> && PYTHONPATH=src uv run python -m utils.oss_aliyun.cli verify --bucket rag-law --prefix md3/
  uv run python -m utils.oss_aliyun.cli put --bucket my-bucket --key a.txt --file ./a.txt
  uv run python -m utils.oss_aliyun.cli get --bucket my-bucket --key a.txt --out ./tmp/a.txt
  uv run python -m utils.oss_aliyun.cli head --bucket my-bucket --key a.txt
  uv run python -m utils.oss_aliyun.cli delete --bucket my-bucket --key a.txt
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from utils.oss_aliyun.client import _ensure_dotenv_loaded
from utils.oss_aliyun.crud import (
    delete_object,
    get_to_file,
    head_object,
    list_all_object_keys,
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

    p_ver = sub.add_parser(
        "verify",
        help="校验 .env 中 OSS 配置并列举对象（不打印 Secret）",
    )
    p_ver.add_argument("--bucket", required=True, help="桶名，如 rag-law")
    p_ver.add_argument(
        "--prefix",
        default="",
        help="列举前缀，如 md3/（与控制台目录一致）",
    )
    p_ver.add_argument(
        "--max-print",
        type=int,
        default=20,
        help="最多打印多少条 key",
    )
    return parser


def _mask_ak(val: str | None) -> str:
    if not val:
        return "(未设置)"
    if len(val) <= 6:
        return "***"
    return val[:4] + "…" + val[-2:]


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

    if args.cmd == "verify":
        _ensure_dotenv_loaded()
        region = os.getenv("OSS_REGION") or ""
        endpoint = os.getenv("OSS_ENDPOINT") or ""
        ak = os.getenv("OSS_ACCESS_KEY_ID") or os.getenv("accessKeyId")
        print("—— 配置摘要（不含 Secret）——")
        print("  OSS_REGION     =", region or "(未设置)")
        print("  OSS_ENDPOINT   =", endpoint or "(未设置，SDK 按 region 构造)")
        print("  AccessKeyId    =", _mask_ak(ak))
        if region == "cn-beijing":
            print("  地域: cn-beijing（华北2 北京，与控制台 oss-cn-beijing 一致）")
        elif region:
            print(
                f"  提示: 若桶在华北2(北京)，OSS_REGION 应为 cn-beijing；当前为 {region!r}，"
                "错误地域可能导致访问异常。",
            )
        try:
            import alibabacloud_oss_v2.exceptions as oss_exc  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover
            oss_exc = None  # type: ignore[assignment]

        try:
            keys = list_all_object_keys(args.bucket, prefix=args.prefix)
        except Exception as exc:
            print("\n—— ListObjectsV2 失败 ——")
            detail: Exception = exc
            if oss_exc and isinstance(exc, oss_exc.OperationError):
                u = exc.unwrap()
                if isinstance(u, Exception):
                    detail = u
            if oss_exc and isinstance(detail, oss_exc.ServiceError):
                print("  status_code:", detail.status_code)
                print("  code:", detail.code)
                print("  message:", detail.message)
                print("  ec:", detail.ec)
                print("  request_id:", detail.request_id)
                print("  endpoint:", detail.request_target)
            else:
                print(type(exc).__name__ + ":", exc)
            print(
                "\n若 message 含「does not belong to you」：多为当前 AccessKey 与控制台登录账号不一致，"
                "或 RAM 用户无该桶 ListObjects 权限。请在 RAM/桶策略中授权后再试。",
            )
            return 1

        md_keys = [k for k in keys if k.lower().endswith(".md")]
        print("\n—— 列举成功 ——")
        print(f"  bucket={args.bucket!r} prefix={args.prefix!r}")
        print(f"  对象总数: {len(keys)}（其中 .md: {len(md_keys)}）")
        for k in keys[: max(0, args.max_print)]:
            print("   ", k)
        if len(keys) > args.max_print:
            print(f"   ... 其余 {len(keys) - args.max_print} 条省略")
        print("\nOK verify")
        return 0

    raise RuntimeError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())

