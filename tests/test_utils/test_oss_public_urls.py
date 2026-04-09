"""utils.oss_aliyun.public_urls"""

from __future__ import annotations

import pytest

from utils.oss_aliyun.public_urls import oss_virtual_host_public_url


def test_oss_virtual_host_public_url_encodes_segments() -> None:
    u = oss_virtual_host_public_url("md3", "cn-beijing", "dir/文件.md")
    assert u == "https://md3.oss-cn-beijing.aliyuncs.com/dir/%E6%96%87%E4%BB%B6.md"


def test_oss_virtual_host_public_url_accepts_oss_region_prefix() -> None:
    u = oss_virtual_host_public_url("b", "oss-cn-hangzhou", "a.md")
    assert u == "https://b.oss-cn-hangzhou.aliyuncs.com/a.md"


def test_oss_virtual_host_public_url_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        oss_virtual_host_public_url("b", "cn-hangzhou", "")
