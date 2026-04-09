"""阿里云 OSS 对象公网访问 URL（虚拟主机样式，未经签名）。"""

from __future__ import annotations

from urllib.parse import quote


def oss_virtual_host_public_url(bucket: str, region: str, object_key: str) -> str:
    """构造 `https://{bucket}.oss-{region}.aliyuncs.com/{key}`，对 key 分段 URL 编码。

    `region` 可为 ``cn-hangzhou`` 或 ``oss-cn-hangzhou``（后者将原样用作 host 段）。
    """
    key = (object_key or "").lstrip("/")
    if not key:
        raise ValueError("object_key 不能为空")
    oss_region = region if region.startswith("oss-") else f"oss-{region}"
    encoded = "/".join(quote(part, safe="") for part in key.split("/"))
    return f"https://{bucket}.{oss_region}.aliyuncs.com/{encoded}"
