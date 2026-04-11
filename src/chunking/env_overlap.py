"""句边界模式下重叠夹紧与 ``boundary_priority_overlap``，与 ``chunking.webui`` 预览一致。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conf.settings import Settings


def effective_boundary_overlap_params(
    chunk_size: int,
    chunk_overlap: int,
    settings: Settings,
) -> tuple[int, int, bool]:
    """与 ``chunking.webui.app._boundary_overlap_params`` 在 ``boundary_aware=True`` 时一致。

    - ``overlap_floor`` / ``overlap_ceiling``：滑窗目标重叠经 ``CHUNK_OVERLAP_MIN``/``MAX`` 与 ``chunk_size-1`` 夹紧。
    - ``boundary_priority_overlap``：当上下界相等（刚性重叠）时为 True，否则取
      ``CHUNK_BOUNDARY_PRIORITY_OVERLAP``。
    """
    req = chunk_overlap
    cap = chunk_size - 1
    st = settings
    base_floor = st.chunk_overlap_min if st.chunk_overlap_min is not None else req
    overlap_floor = min(req, base_floor)
    if st.chunk_overlap_max is not None:
        overlap_ceiling = min(cap, st.chunk_overlap_max)
    else:
        overlap_ceiling = min(cap, req)
    rigid_overlap = overlap_floor == overlap_ceiling
    boundary_priority_overlap = rigid_overlap or st.chunk_boundary_priority_overlap
    return overlap_floor, overlap_ceiling, boundary_priority_overlap
