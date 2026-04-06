"""句边界对齐：在滑窗初值上按截止符微调首尾，见 doc/chunk/句边界对齐切分.md。"""

from __future__ import annotations

from collections.abc import Iterator

# 。！？；与换行；另含 \r 以便不改动字符串长度即可识别 Windows 换行
BOUNDARY_CHARS: frozenset[str] = frozenset("。！？；\n\r")

# 强句界无候选时：±max_probe 内最近弱边界（标点、空格等），块起点/右开终点在弱字符之后
WEAK_BOUNDARY_CHARS: frozenset[str] = frozenset(
    " \t，、,.:;:!?-_（）【】《》「」『』〈〉""''…·％%＆&"
)

# 句首/句尾「可接受」断点（强 ∪ 弱），见 doc/chunk/句边界块链与二次对齐方案.md
ACCEPTABLE_BOUNDARY_CHARS: frozenset[str] = BOUNDARY_CHARS | WEAK_BOUNDARY_CHARS

DEFAULT_MAX_PROBE: int = 30
DEFAULT_MAX_BOUNDARY_SCAN: int = 800


def _is_boundary(ch: str) -> bool:
    return ch in BOUNDARY_CHARS


def _is_weak_boundary(ch: str) -> bool:
    return ch in WEAK_BOUNDARY_CHARS


def is_acceptable_head(text: str, s: int, *, n: int | None = None) -> bool:
    """句首合法：s==0 或 text[s-1] 为可接受断点字符（起点在断点之后）。"""
    n = len(text) if n is None else n
    if s <= 0:
        return True
    if s > n:
        return False
    return text[s - 1] in ACCEPTABLE_BOUNDARY_CHARS


def is_acceptable_tail(text: str, e: int, *, n: int | None = None) -> bool:
    """句尾合法：e==n 或 text[e-1] 为可接受断点字符（右开区间末字）。"""
    n = len(text) if n is None else n
    if e <= 0:
        return False
    if e >= n:
        return True
    return text[e - 1] in ACCEPTABLE_BOUNDARY_CHARS


def _align_start_strong(
    text: str,
    s0: int,
    max_probe: int,
    *,
    n: int,
) -> int | None:
    """在 ±max_probe 内仅强句界；有候选则 min|Δ|，平局向后；无则 None。"""
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
    return None


def _align_start_weak(
    text: str,
    s0: int,
    max_probe: int,
    *,
    n: int,
) -> int | None:
    """强句界无候选时：±max_probe 内最近弱边界（起点在弱字符之后）；平局向后（更小下标）。"""
    lo = max(0, s0 - max_probe)
    hi = min(n, s0 + max_probe)
    best: int | None = None
    best_d: int | None = None
    for i in range(lo, hi):
        if not _is_weak_boundary(text[i]):
            continue
        cand = i + 1
        if cand > n:
            continue
        d = abs(cand - s0)
        if best_d is None or d < best_d or (d == best_d and cand < (best or n + 1)):
            best = cand
            best_d = d
    return best


def adjust_start(
    text: str,
    s0: int,
    max_probe: int = DEFAULT_MAX_PROBE,
    *,
    n: int | None = None,
) -> int:
    """
    强句界 → 弱标点/空格 → 保持初值 s0。
    在初值 s0 两侧各 max_probe 内：强句界取 |Δ| 最小；无则弱边界取 |Δ| 最小；再无则 s0。
    """
    n = len(text) if n is None else n
    if s0 <= 0:
        return 0
    if s0 > n:
        return min(s0, n)

    s = _align_start_strong(text, s0, max_probe, n=n)
    if s is not None:
        return s
    s = _align_start_weak(text, s0, max_probe, n=n)
    if s is not None:
        return s
    return s0


def adjust_start_extended(
    text: str,
    s0: int,
    max_probe: int,
    max_boundary_scan: int,
    *,
    n: int | None = None,
) -> int:
    """
    先局部 adjust_start；若句首仍不可接受（且 s>0），在 ±max_boundary_scan 内再做强→弱。
    """
    n = len(text) if n is None else n
    s = adjust_start(text, s0, max_probe, n=n)
    if is_acceptable_head(text, s, n=n):
        return s
    if s0 <= 0:
        return s
    scan = max(max_probe, max_boundary_scan)
    s = _align_start_strong(text, s0, scan, n=n)
    if s is not None:
        return s
    s = _align_start_weak(text, s0, scan, n=n)
    if s is not None:
        return s
    return adjust_start(text, s0, max_probe, n=n)


def _align_end_strong(
    text: str,
    e0: int,
    max_probe: int,
    *,
    n: int,
) -> int | None:
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
    return None


def _align_end_weak(
    text: str,
    e0: int,
    max_probe: int,
    *,
    n: int,
) -> int | None:
    if e0 >= n:
        return n
    lo = max(0, e0 - max_probe)
    hi = min(n, e0 + max_probe)
    best: int | None = None
    best_d: int | None = None
    for i in range(lo, hi):
        if not _is_weak_boundary(text[i]):
            continue
        cand = i + 1
        if cand > n:
            continue
        d = abs(cand - e0)
        if best_d is None or d < best_d or (d == best_d and cand < (best or n + 1)):
            best = cand
            best_d = d
    return best


def adjust_end(
    text: str,
    e0: int,
    max_probe: int = DEFAULT_MAX_PROBE,
    *,
    n: int | None = None,
) -> int:
    """强句界 → 弱标点/空格 → 保持初值 e0。"""
    n = len(text) if n is None else n
    if e0 >= n:
        return n
    if e0 <= 0:
        return min(max(e0, 0), n)

    e = _align_end_strong(text, e0, max_probe, n=n)
    if e is not None:
        return e
    e = _align_end_weak(text, e0, max_probe, n=n)
    if e is not None:
        return e
    return e0


def adjust_end_extended(
    text: str,
    e0: int,
    max_probe: int,
    max_boundary_scan: int,
    *,
    n: int | None = None,
) -> int:
    """先局部 adjust_end；若句尾仍不可接受且 e<n，在 ±max_boundary_scan 内再做强→弱。"""
    n = len(text) if n is None else n
    e = adjust_end(text, e0, max_probe, n=n)
    if is_acceptable_tail(text, e, n=n):
        return e
    if e0 >= n:
        return n
    scan = max(max_probe, max_boundary_scan)
    e2 = _align_end_strong(text, e0, scan, n=n)
    if e2 is not None:
        return e2
    e2 = _align_end_weak(text, e0, scan, n=n)
    if e2 is not None:
        return e2
    return adjust_end(text, e0, max_probe, n=n)


def _clamp_start_for_overlap(
    s_adj: int,
    prev_end: int | None,
    overlap_floor: int,
) -> int:
    """
    与上一块至少重叠 overlap_floor 个字符（仅下界，兼容旧调用）。
    等价于 overlap_ceiling=prev_end（不限制重叠上界，仅保证 start>=0）。
    """
    if prev_end is None:
        return s_adj
    return _clamp_start_to_overlap_range(s_adj, prev_end, overlap_floor, prev_end)


def _clamp_start_to_overlap_range(
    s_adj: int,
    prev_end: int | None,
    overlap_floor: int,
    overlap_ceiling: int,
) -> int:
    """
    重叠 L = prev_end - start 满足 overlap_floor <= L <= overlap_ceiling，
    即 prev_end - overlap_ceiling <= start <= prev_end - overlap_floor。
    """
    if prev_end is None:
        return s_adj
    if overlap_floor > overlap_ceiling:
        raise ValueError("overlap_floor 不能大于 overlap_ceiling")
    hi = prev_end - overlap_floor
    lo = prev_end - overlap_ceiling
    if hi < 0:
        return s_adj
    if lo < 0:
        lo = 0
    return min(max(s_adj, lo), hi)


def _overlap_in_range(
    s: int,
    prev_end: int | None,
    overlap_floor: int,
    overlap_ceiling: int,
) -> bool:
    if prev_end is None:
        return True
    L = prev_end - s
    return overlap_floor <= L <= overlap_ceiling


def _reconcile_start_after_repass(
    text: str,
    s_c: int,
    prev_end: int | None,
    overlap_floor: int,
    overlap_ceiling: int,
    *,
    boundary_priority_overlap: bool,
    clamp_adjust_max_rounds: int,
    max_probe: int,
    max_boundary_scan: int,
    n: int,
) -> int:
    """
    夹紧后再对齐得到的 s_c：按重叠区间与 boundary_priority_overlap 协调最终起点。
    """
    if prev_end is None:
        return s_c
    if _overlap_in_range(s_c, prev_end, overlap_floor, overlap_ceiling):
        return s_c
    if boundary_priority_overlap:
        return s_c
    s_d = _clamp_start_to_overlap_range(s_c, prev_end, overlap_floor, overlap_ceiling)
    if clamp_adjust_max_rounds < 2 or s_d == s_c:
        return s_d
    s_e = adjust_start_extended(text, s_d, max_probe, max_boundary_scan, n=n)
    if _overlap_in_range(s_e, prev_end, overlap_floor, overlap_ceiling):
        return s_e
    if boundary_priority_overlap:
        return s_e
    return _clamp_start_to_overlap_range(s_e, prev_end, overlap_floor, overlap_ceiling)


def _pipeline_start(
    text: str,
    s0: int,
    prev_end: int | None,
    overlap_floor: int,
    overlap_ceiling: int,
    *,
    max_probe: int,
    max_boundary_scan: int,
    boundary_priority_overlap: bool,
    clamp_adjust_max_rounds: int,
    n: int,
) -> int:
    """第一次扩展对齐 → 重叠夹紧 → 第二次扩展对齐 → 协调。"""
    s_a = adjust_start_extended(text, s0, max_probe, max_boundary_scan, n=n)
    s_b = _clamp_start_to_overlap_range(s_a, prev_end, overlap_floor, overlap_ceiling)
    s_c = adjust_start_extended(text, s_b, max_probe, max_boundary_scan, n=n)
    return _reconcile_start_after_repass(
        text,
        s_c,
        prev_end,
        overlap_floor,
        overlap_ceiling,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
        max_probe=max_probe,
        max_boundary_scan=max_boundary_scan,
        n=n,
    )


def _validate_boundary_aware_params(
    chunk_size: int,
    chunk_overlap: int,
    overlap_floor: int,
    overlap_ceiling: int,
    max_probe: int,
    max_boundary_scan: int,
) -> None:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")
    if overlap_floor > chunk_overlap:
        raise ValueError(
            "overlap_floor 不能大于 chunk_overlap（滑窗步长由 chunk_size - chunk_overlap 决定）"
        )
    if overlap_floor > overlap_ceiling:
        raise ValueError("overlap_floor 不能大于 overlap_ceiling")
    if overlap_ceiling >= chunk_size:
        raise ValueError("overlap_ceiling 必须小于 chunk_size")
    if max_boundary_scan < max_probe:
        raise ValueError(
            "max_boundary_scan 经裁剪后仍须 >= max_probe（请增大 chunk_size 或显式提高 max_boundary_scan）"
        )


def _effective_max_boundary_scan(
    chunk_size: int,
    max_probe: int,
    max_boundary_scan: int | None,
) -> int:
    """默认 min(chunk_size,800)，且不小于 max_probe、不超过 chunk_size。"""
    raw = (
        max_boundary_scan
        if max_boundary_scan is not None
        else min(chunk_size, DEFAULT_MAX_BOUNDARY_SCAN)
    )
    raw = min(chunk_size, raw)
    return max(max_probe, raw)


def iter_boundary_aware_diag_rows(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    overlap_floor: int | None = None,
    overlap_ceiling: int | None = None,
    max_probe: int = DEFAULT_MAX_PROBE,
    max_boundary_scan: int | None = None,
    boundary_priority_overlap: bool = False,
    clamp_adjust_max_rounds: int = 2,
) -> Iterator[dict[str, object]]:
    """
    与 `iter_text_slices_boundary_aware` 同逻辑，每条产出一块并附诊断字段（供 analyze 脚本等）。
    """
    floor = chunk_overlap if overlap_floor is None else overlap_floor
    ceiling = chunk_overlap if overlap_ceiling is None else overlap_ceiling
    scan = _effective_max_boundary_scan(chunk_size, max_probe, max_boundary_scan)
    _validate_boundary_aware_params(chunk_size, chunk_overlap, floor, ceiling, max_probe, scan)
    n = len(text)
    if n == 0:
        return
    from chunking.split import iter_text_slices

    raw = list(iter_text_slices(text, chunk_size, chunk_overlap))
    prev_end: int | None = None

    for _piece, s0, e0 in raw:
        s_aligned = adjust_start_extended(text, s0, max_probe, scan, n=n)
        s_after_first_clamp = _clamp_start_to_overlap_range(
            s_aligned, prev_end, floor, ceiling
        )
        clamp_moved = s_after_first_clamp != s_aligned

        s_adj = _pipeline_start(
            text,
            s0,
            prev_end,
            floor,
            ceiling,
            max_probe=max_probe,
            max_boundary_scan=scan,
            boundary_priority_overlap=boundary_priority_overlap,
            clamp_adjust_max_rounds=clamp_adjust_max_rounds,
            n=n,
        )

        e_adj = adjust_end_extended(text, e0, max_probe, scan, n=n)
        fallback = False

        if s_adj >= e_adj:
            e_adj = min(s_adj + chunk_size, n)
            e_adj = adjust_end_extended(text, e_adj, max_probe, scan, n=n)
        if s_adj >= e_adj:
            s_adj, e_adj = s0, e0
            fallback = True
            s_adj = _pipeline_start(
                text,
                s0,
                prev_end,
                floor,
                ceiling,
                max_probe=max_probe,
                max_boundary_scan=scan,
                boundary_priority_overlap=boundary_priority_overlap,
                clamp_adjust_max_rounds=clamp_adjust_max_rounds,
                n=n,
            )
            e_adj = adjust_end_extended(text, e0, max_probe, scan, n=n)
        if s_adj >= e_adj:
            e_adj = min(s_adj + chunk_size, n)
            e_adj = adjust_end_extended(text, e_adj, max_probe, scan, n=n)
        e_adj = min(e_adj, n)
        if s_adj >= e_adj and s_adj < n:
            e_adj = s_adj + 1
        if s_adj >= n:
            continue
        if s_adj >= e_adj:
            continue
        piece = text[s_adj:e_adj]
        row = {
            "s0": s0,
            "e0": e0,
            "s": s_adj,
            "e": e_adj,
            "s_aligned": s_aligned,
            "clamp_moved": clamp_moved,
            "fallback": fallback,
            "prev_end": prev_end,
            "piece": piece,
        }
        prev_end = e_adj
        yield row


def iter_text_slices_boundary_aware(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    overlap_floor: int | None = None,
    overlap_ceiling: int | None = None,
    max_probe: int = DEFAULT_MAX_PROBE,
    max_boundary_scan: int | None = None,
    boundary_priority_overlap: bool = False,
    clamp_adjust_max_rounds: int = 2,
) -> Iterator[tuple[str, int, int]]:
    """
    先按 `iter_text_slices` 取初值，再对每段做句首/句尾对齐（强→弱→初值），扩展扫描，
    重叠夹紧后再对句首做一次扩展对齐并协调重叠；保证与上一块重叠在 [overlap_floor, overlap_ceiling]
    （在 boundary_priority_overlap=False 且协调成功时；否则可能越界）。
    """
    for row in iter_boundary_aware_diag_rows(
        text,
        chunk_size,
        chunk_overlap,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        max_probe=max_probe,
        max_boundary_scan=max_boundary_scan,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
    ):
        yield row["piece"], row["s"], row["e"]  # type: ignore[misc]
