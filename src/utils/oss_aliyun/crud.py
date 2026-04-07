"""Basic CRUD helpers for Aliyun OSS objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.oss_aliyun.client import build_client_from_env


@dataclass(frozen=True)
class OssObjectMeta:
    etag: str | None
    content_length: int | None
    last_modified: str | None


def put_bytes(bucket: str, key: str, body: bytes) -> Any:
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    return client.put_object(
        oss.PutObjectRequest(
            bucket=bucket,
            key=key,
            body=body,
        )
    )


def put_file(bucket: str, key: str, file_path: Path) -> Any:
    data = file_path.read_bytes()
    return put_bytes(bucket=bucket, key=key, body=data)


def get_bytes(bucket: str, key: str) -> bytes:
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    out = client.get_object(oss.GetObjectRequest(bucket=bucket, key=key))
    return out.body.read()


def get_to_file(bucket: str, key: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(get_bytes(bucket=bucket, key=key))
    return output


def head_object(bucket: str, key: str) -> OssObjectMeta:
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    out = client.head_object(oss.HeadObjectRequest(bucket=bucket, key=key))
    return OssObjectMeta(
        etag=getattr(out, "etag", None),
        content_length=getattr(out, "content_length", None),
        last_modified=getattr(out, "last_modified", None),
    )


def delete_object(bucket: str, key: str) -> Any:
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    return client.delete_object(oss.DeleteObjectRequest(bucket=bucket, key=key))

