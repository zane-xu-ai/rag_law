"""句边界对齐：在滑窗初值上按截止符微调首尾，见 doc/chunk/句边界对齐切分.md。"""

from __future__ import annotations

from collections.abc import Iterator

# 。！？；与换行；另含 \r 以便不改动字符串长度即可识别 Windows 换行
BOUNDARY_CHARS: frozenset[str] = frozenset("。！？；\n\r")

DEFAULT_MAX_PROBE: int = 30


def _is_boundary(ch: str) -> bool:
    return ch in BOUNDARY_CHARS


def adjust_start(
    text: str,
    s0: int,
    max_probe: int = DEFAULT_MAX_PROBE,
    *,
    n: int | None = None,
) -> int:
    """
    在初值 s0 两侧各 max_probe 内找截止符，取位移绝对值较小的一侧；平局优先向后（更贴近句首补全）。
    两侧均无效则返回 s0。
    """
    n = len(text) if n is None else n
    if s0 <= 0:
        s0 = 0
    if s0 > n:
        return min(s0, n)

    lo = max(0, s0 - max_probe)
    k_back: int | None = None
    for i in range(s0 - 1, lo - 1, -1):
        if i < 0:
            break
        if _is_boundary(text[i]):
            k_back = i
            break
    s_back = k_back + 1 if k_back is not None else None

    hi = min(n, s0 + max_probe)
    k_fwd: int | None = None
    for j in range(s0, hi):
        if _is_boundary(text[j]):
            k_fwd = j
            break
    s_fwd = k_fwd + 1 if k_fwd is not None else None

    if s_back is not None and s_fwd is not None:
        db = abs(s_back - s0)
        df = abs(s_fwd - s0)
        if db < df:
            return s_back
        if df < db:
            return s_fwd
        return s_back
    if s_back is not None:
        return s_back
    if s_fwd is not None:
        return s_fwd
    return s0


def adjust_end(
    text: str,
    e0: int,
    max_probe: int = DEFAULT_MAX_PROBE,
    *,
    n: int | None = None,
) -> int:
    """
    右开终点 e0：在两侧各 max_probe 内对齐到「截止符之后」；e0==len(text) 时保持。
    平局优先向后候选。
    """
    n = len(text) if n is None else n
    if e0 >= n:
        return n
    if e0 <= 0:
        return min(max(e0, 0), n)

    lo = max(0, e0 - max_probe)
    k_back: int | None = None
    for i in range(e0 - 1, lo - 1, -1):
        if i < 0:
            break
        if _is_boundary(text[i]):
            k_back = i
            break
    e_back = k_back + 1 if k_back is not None else None

    hi = min(n, e0 + max_probe)
    k_fwd: int | None = None
    for j in range(e0, hi):
        if _is_boundary(text[j]):
            k_fwd = j
            break
    e_fwd = k_fwd + 1 if k_fwd is not None else None

    if e_back is not None and e_fwd is not None:
        db = abs(e_back - e0)
        df = abs(e_fwd - e0)
        if db < df:
            return e_back
        if df < db:
            return e_fwd
        return e_back
    if e_back is not None:
        return e_back
    if e_fwd is not None:
        return e_fwd
    return e0


def _clamp_start_for_overlap(
    s_adj: int,
    prev_end: int | None,
    overlap_floor: int,
) -> int:
    """
    与上一块至少重叠 overlap_floor 个字符：需 prev_end - start >= overlap_floor，
    即 start <= prev_end - overlap_floor（起点不得晚于该上界）。
    """
    if prev_end is None:
        return s_adj
    upper = prev_end - overlap_floor
    if upper < 0:
        return s_adj
    return min(s_adj, upper)


def iter_text_slices_boundary_aware(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    overlap_floor: int | None = None,
    max_probe: int = DEFAULT_MAX_PROBE,
) -> Iterator[tuple[str, int, int]]:
    """
    先按 `iter_text_slices` 取初值，再对每段做句首/句尾对齐，并保证与上一块
    重叠不少于 overlap_floor（默认等于 chunk_overlap，即滑窗目标重叠）。

    overlap_floor 可小于 chunk_overlap：句界对齐后允许实际重叠在
    [overlap_floor, chunk_overlap] 间浮动（例如目标 100、下界 60）。
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")
    floor = chunk_overlap if overlap_floor is None else overlap_floor
    if floor > chunk_overlap:
        raise ValueError(
            "overlap_floor 不能大于 chunk_overlap（滑窗步长由 chunk_size - chunk_overlap 决定）"
        )
    n = len(text)
    if n == 0:
        return
    from chunking.split import iter_text_slices

    raw = list(iter_text_slices(text, chunk_size, chunk_overlap))
    prev_end: int | None = None

    for _piece, s0, e0 in raw:
        s_aligned = adjust_start(text, s0, max_probe, n=n)
        s_adj = _clamp_start_for_overlap(s_aligned, prev_end, floor)

        e_adj = adjust_end(text, e0, max_probe, n=n)

        if s_adj >= e_adj:
            s_adj, e_adj = s0, e0
            s_adj = _clamp_start_for_overlap(s_adj, prev_end, floor)
        if s_adj >= e_adj:
            e_adj = min(s_adj + chunk_size, n)
        e_adj = min(e_adj, n)
        if s_adj >= e_adj and s_adj < n:
            e_adj = s_adj + 1
        if s_adj >= n:
            continue
        if s_adj >= e_adj:
            continue
        piece = text[s_adj:e_adj]
        yield piece, s_adj, e_adj
        prev_end = e_adj
