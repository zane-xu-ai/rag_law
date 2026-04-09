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


def list_all_object_keys(
    bucket: str,
    *,
    prefix: str = "",
) -> list[str]:
    """分页列举桶内全部对象 key（仅 key 列表，升序由调用方决定）。"""
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    out: list[str] = []
    token: str | None = None
    while True:
        req = oss.ListObjectsV2Request(
            bucket=bucket,
            prefix=prefix or None,
            continuation_token=token,
            max_keys=500,
        )
        result = client.list_objects_v2(req)
        for obj in result.contents or []:
            if obj.key:
                out.append(obj.key)
        if not result.is_truncated:
            break
        token = result.next_continuation_token
        if not token:
            break
    return out


def download_object_to_file(bucket: str, key: str, filepath: Path) -> Path:
    """流式下载对象到本地路径（父目录不存在则创建）。"""
    import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]

    client = build_client_from_env()
    filepath = filepath.expanduser().resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    client.get_object_to_file(oss.GetObjectRequest(bucket=bucket, key=key), str(filepath))
    return filepath

