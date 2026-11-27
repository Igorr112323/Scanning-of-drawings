"""Shared revolution-geometry extraction for all input paths.

Both the vector-PDF parser (:mod:`core.pdf_parser`) and the scan pipeline
(:mod:`core.scan_pipeline`) funnel through :func:`extract_revolution`:
locate the dash-dot axis (horizontal or vertical), transpose when needed,
and reconstruct the half-profile + optional centre-bore diameter.
"""

from __future__ import annotations

import math

from core.models import ElementType, ProfilePoint, VectorElement


# --------------------------------------------------------------------------- #
# axis chain detection (traced dash-dot centre lines) — shared with corpus   #
# --------------------------------------------------------------------------- #
CHAIN_MIN_PIECES = 4      # collinear pieces needed for a dash-dot chain
CHAIN_MAX_GAP_MM = 8.0    # GOST dash-dot gaps are 1.5–3 mm; 8 mm is generous
CHAIN_MIN_COVERAGE = 0.45 # dash-dot cadence is ~70-80% coverage
CHAIN_Y_BAND_MM = 3.0     # vectorized scans jitter; GOST text pitch is >=5 mm
CHAIN_MIN_SPAN_MM = 120.0 # absolute — a revolution axis spans the view, not the page
CHAIN_SCORE_FULL_MM = 250.0  # span at which the screen axis score saturates at 1.0


def detect_axis_chain(horiz: list[tuple[float, float, float]],
                      min_span_mm: float = CHAIN_MIN_SPAN_MM) -> tuple[float, float] | None:
    """GOST centre lines whose dashes/dots are exported as separate thin
    segments (auto-traced scans) carry no dash attribute at all — detect the
    collinear chain itself: ≥4 pieces in one y band with ≤8 mm gaps and an
    absolute span of at least `min_span_mm` (a revolution axis spans the
    *view*, so page-width-relative thresholds are wrong for A2/A3 sheets).

    Returns (axis_y_mm, span_mm) where axis_y_mm is the *mean* undisturbed y
    of the winning pieces — band quantization must never leak into the mirror
    symmetry comparison."""
    bands: dict[int, list[tuple[float, float, float]]] = {}
    for x0, y, x1 in horiz:
        bands.setdefault(round(y / CHAIN_Y_BAND_MM), []).append((x0, y, x1))

    best: tuple[float, float] | None = None

    def qualify(run: list[tuple[float, float, float]]) -> None:
        nonlocal best
        pieces = len(run)
        start = run[0][0]
        end = max(s[2] for s in run)
        span = end - start
        cover = sum(s[2] - s[0] for s in run)
        if pieces >= CHAIN_MIN_PIECES and span >= min_span_mm and cover / span >= CHAIN_MIN_COVERAGE:
            axis_y = sum(s[1] for s in run) / pieces
            if best is None or span > best[1]:
                best = (axis_y, span)

    for band, segs in bands.items():
        segs.sort(key=lambda s: s[0])
        run: list[tuple[float, float, float]] = [segs[0]]
        run_end = segs[0][2]
        for s in segs[1:]:
            if s[0] - run_end <= CHAIN_MAX_GAP_MM:
                run.append(s)
                run_end = max(run_end, s[2])
            else:
                qualify(run)
                run = [s]
                run_end = s[2]
        qualify(run)
    return best


def find_axis_chain(elements: list["VectorElement"]):
    """Chain fallback for traced pages whose centre line carries no dash
    attribute: collect every horizontal stroke (any width) and run the
    collinear-chain detector. Returns (axis_y_mm, span_mm) or None."""
    horiz: list[tuple[float, float, float]] = []
    for e in elements:
        if len(e.points) != 2 or e.type is ElementType.TEXT:
            continue
        (x0, y0), (x1, y1) = e.points
        if abs(y1 - y0) <= 0.5:
            horiz.append((min(x0, x1), (y0 + y1) / 2.0, max(x0, x1)))
    return detect_axis_chain(horiz)


def find_axis(elements: list[VectorElement]) -> tuple[str | None, float | None]:
    """Locate the revolution axis: the longest dash-dot line on the sheet.

    Returns ("horizontal", y_mm) or ("vertical", x_mm); (None, None) if absent.

    Fallback for auto-traced drawings whose dash-dot centre line is exported
    as separate thin strokes with no dash attribute (seen on the zenodo
    open_mech pages): the collinear chain is detected directly.
    """
    best_len = 0.0
    best: tuple[str | None, float | None] = (None, None)
    for e in elements:
        if e.type is not ElementType.AXIS or len(e.points) != 2:
            continue
        (x0, y0), (x1, y1) = e.points
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= best_len:
            continue
        if abs(y1 - y0) <= abs(x1 - x0):
            best = ("horizontal", (y0 + y1) / 2.0)
        else:
            best = ("vertical", (x0 + x1) / 2.0)
        best_len = length
    if best[0] is not None:
        return best
    chain = find_axis_chain(elements)
    if chain is not None:
        return ("horizontal", chain[0])
    return best


def transpose_elements(elements: list[VectorElement]) -> list[VectorElement]:
    """Swap x/y of every element so a vertical axis becomes horizontal.

    Profile reconstruction then works unchanged; sheet preview/overlay keep the
    original (untransposed) elements — only the geometry pipeline uses these.
    """
    out: list[VectorElement] = []
    for e in elements:
        pts = [(y, x) for (x, y) in e.points]
        bbox = None
        if e.bbox:
            x0, y0, x1, y1 = e.bbox
            bbox = (y0, x0, y1, x1)
        out.append(VectorElement(
            id=e.id, type=e.type, points=pts,
            stroke_width=e.stroke_width, dash=e.dash,
            text=e.text, bbox=bbox, ocr_confidence=e.ocr_confidence,
        ))
    return out


def _line_y(line, x: float) -> float:
    """Y of the (xa, xb, ya, yb) line at x (extrapolates beyond the ends)."""
    xa, xb, ya, yb = line
    if xb - xa < 1e-9:
        return ya
    t = (x - xa) / (xb - xa)
    return ya + (yb - ya) * t


def _incl_angle(line) -> float:
    xa, xb, ya, yb = line
    return math.degrees(math.atan2(yb - ya, xb - xa)) % 180.0


def _perp_cos(angle_deg: float) -> float:
    """cos of the acute angle with the horizontal (vertical-line safe)."""
    acute = min(angle_deg, 180.0 - angle_deg)
    return abs(math.cos(math.radians(acute)))


def _mix_cos(a1: float, a2: float) -> float:
    """Mean per-line perpendicular cosine — never average the raw angles
    (near-0° and near-180° are the same family; their mean is ~90°)."""
    return (_perp_cos(a1) + _perp_cos(a2)) / 2.0


def _sample_gap(l1, l2, x: float) -> float:
    """Vertical gap between the two lines at x (positive = l2 above l1)."""
    return _line_y(l2, x) - _line_y(l1, x)


def _merge_collinear(
    lines: list[tuple[float, float, float, float]],
    angle_tol_deg: float = 2.0,
    offset_tol: float = 0.6,
    gap_tol: float = 4.0,
) -> list[tuple[float, float, float, float]]:
    """Union fragments of the same physical stroke.

    Scans break long lines into sub-pixel-gapped fragments; vector PDFs emit
    exact segments already (no-ops there). Two fragments merge when they are
    near-collinear (angle + constant perpendicular offset) and their x-spans
    overlap or are separated by less than ``gap_tol`` (mm).
    Lines are (xa, xb, y@xa, y@xb) with xa <= xb.
    """
    items = list(lines)
    merged = True
    while merged:
        merged = False
        for i in range(len(items)):
            if merged:
                break
            for j in range(i + 1, len(items)):
                union = _try_merge(items[i], items[j], angle_tol_deg,
                                   offset_tol, gap_tol)
                if union is not None:
                    items[i] = union
                    items.pop(j)
                    merged = True
                    break
    return items


def _try_merge(l1, l2, angle_tol_deg: float, offset_tol: float, gap_tol: float):
    xa1, xb1, ya1, yb1 = l1
    xa2, xb2, ya2, yb2 = l2
    a1, a2 = _incl_angle(l1), _incl_angle(l2)
    diff = abs(a1 - a2)
    if diff > angle_tol_deg and abs(diff - 180.0) > angle_tol_deg:
        return None
    lo, hi = max(xa1, xa2), min(xb1, xb2)
    if lo <= hi:
        probe = (lo + hi) / 2.0
    else:
        # disjoint spans: probe the middle of the gap
        if xa1 <= xa2:
            probe = (xb1 + xa2) / 2.0 if xb1 < xa2 else (xa2 + xb1) / 2.0
            gap = xa2 - xb1
        else:
            probe = (xb2 + xa1) / 2.0 if xb2 < xa1 else (xa1 + xb2) / 2.0
            gap = xa1 - xb2
        if gap > gap_tol:
            return None
    cos_a = _mix_cos(a1, a2)
    if abs(_sample_gap(l1, l2, probe)) * cos_a > offset_tol:
        return None
    # merged span covers both; endpoint Ys come from the lines covering each
    # end (average when both do) — never from extrapolating a fragment
    # past its own span
    new_lo, new_hi = min(xa1, xa2), max(xb1, xb2)

    def _at_end(x: float) -> float:
        ys = []
        if xa1 - 1e-6 <= x <= xb1 + 1e-6:
            ys.append(_line_y(l1, x))
        if xa2 - 1e-6 <= x <= xb2 + 1e-6:
            ys.append(_line_y(l2, x))
        return sum(ys) / len(ys)

    return (new_lo, new_hi, _at_end(new_lo), _at_end(new_hi))


def _pair_union(l1, l2, angle_tol_deg: float, min_gap: float,
                max_gap: float, overlap_frac: float):
    """Collapse the two detected edges of one drawn stroke into its centre.

    Thick GOST main lines rasterise as two parallel edge detections separated
    by the stroke width (0.3–0.7 mm). Averaging the pair recovers the drawn
    feature to ~0.1 mm. Pairs whose gap varies along their overlap (noise,
    crossing strokes) or that share too little x-span are left alone.
    """
    xa1, xb1, ya1, yb1 = l1
    xa2, xb2, ya2, yb2 = l2
    a1, a2 = _incl_angle(l1), _incl_angle(l2)
    diff = abs(a1 - a2)
    if diff > angle_tol_deg and abs(diff - 180.0) > angle_tol_deg:
        return None
    o = min(xb1, xb2) - max(xa1, xa2)
    shorter = min(xb1 - xa1, xb2 - xa2)
    if shorter <= 1e-9 or o < overlap_frac * shorter:
        return None
    lo, hi = max(xa1, xa2), min(xb1, xb2)
    cos_a = _mix_cos(a1, a2)
    d_lo = _sample_gap(l1, l2, lo) * cos_a
    d_hi = _sample_gap(l1, l2, hi) * cos_a
    if abs(d_lo - d_hi) > 0.15:
        return None  # gap varies — not the two edges of one stroke
    gap = (d_lo + d_hi) / 2.0
    if abs(gap) < min_gap or abs(gap) > max_gap:
        return None
    new_lo, new_hi = min(xa1, xa2), max(xb1, xb2)
    s = gap  # signed offset of l2 over l1 (constant, by the check above)

    def _at_end(x: float) -> float:
        y1 = _line_y(l1, x) if xa1 - 1e-6 <= x <= xb1 + 1e-6 else None
        y2 = _line_y(l2, x) if xa2 - 1e-6 <= x <= xb2 + 1e-6 else None
        if y1 is not None and y2 is not None:
            return (y1 + y2) / 2.0
        if y1 is not None:
            return y1 + s / 2.0  # flat extension, not a tilted guess
        return y2 - s / 2.0

    return (new_lo, new_hi, _at_end(new_lo), _at_end(new_hi))


def _union_parallel_edges(
    lines: list[tuple[float, float, float, float]],
    angle_tol_deg: float = 1.0,
    min_gap: float = 0.15,
    max_gap: float = 1.5,
    overlap_frac: float = 0.6,
) -> list[tuple[float, float, float, float]]:
    out = list(lines)
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            if changed:
                break
            for j in range(i + 1, len(out)):
                union = _pair_union(out[i], out[j], angle_tol_deg,
                                    min_gap, max_gap, overlap_frac)
                if union is not None:
                    out[i] = union
                    out.pop(j)
                    changed = True
                    break
    return out


def build_half_profile(
    elements: list[VectorElement], axis_y: float
) -> tuple[list[ProfilePoint], float | None]:
    """Reconstruct the half-profile (x, r) and optional centre-bore diameter.

    Radii are interpolated along CONTOUR line segments of any slope (a drawn
    45° chamfer is a straight line, so the reconstruction stays exact). The
    outline of a body of revolution is evaluated at every breakpoint produced
    by the segments; each elementary interval must be covered — otherwise this
    is not a simple body of revolution and an empty profile is returned
    rather than a guess. Works for shafts, flanges, bushings and rings.

    Inner contours spanning the whole length at constant radius are recognised
    as bore walls: the part is hollow and the bore diameter is returned.
    """
    r_tol = 0.01  # mm
    raw_lines: list[tuple[float, float, float, float]] = []  # xa, xb, y(xa), y(xb)
    breakpoints: set[float] = set()
    for e in elements:
        if e.type != ElementType.CONTOUR or len(e.points) != 2:
            continue
        (x0, y0), (x1, y1) = e.points
        if abs(x1 - x0) < 1e-6:
            continue  # vertical shoulder: re-collected below
        xa, xb = (x0, x1) if x0 < x1 else (x1, x0)
        ya, yb = (y0, y1) if x0 < x1 else (y1, y0)
        if max(ya, yb) >= axis_y - 0.05:
            if min(ya, yb) >= axis_y - 0.05:
                continue  # entirely in/below the lower half
        # strokes lying on the axis are centre-line debris, not surfaces —
        # a genuine outline never runs along the axis for a measurable length
        if axis_y - max(ya, yb) < 0.6 and (xb - xa) > 0.5:
            continue
        raw_lines.append((xa, xb, ya, yb))
    lines = _union_parallel_edges(_merge_collinear(raw_lines))
    breakpoints = set()
    for xa, xb, _, _ in lines:
        breakpoints.update((xa, xb))
    for e in elements:
        if e.type == ElementType.CONTOUR and len(e.points) == 2:
            (x0, y0), (x1, y1) = e.points
            if abs(x1 - x0) < 1e-6:
                breakpoints.add(x0)  # vertical shoulders still split intervals

    if len(breakpoints) < 2:
        return [], None
    # breakpoints beyond the strokes carry no geometry — drop them (end slivers
    # from noise/fragment endpoints); real gaps between strokes stay fatal
    x_lo = min(l[0] for l in lines)
    x_hi = max(l[1] for l in lines)
    bps = [b for b in sorted(breakpoints) if b >= x_lo - 1e-9 and b <= x_hi + 1e-9]
    if len(bps) < 2:
        return [], None

    def _covering(x: float) -> list[tuple[float, float, float, float]]:
        return [ln for ln in lines if ln[0] - r_tol <= x <= ln[1] + r_tol]

    def _radii_at(x: float, covering) -> list[float]:
        out = []
        for xa, xb, ya, yb in covering:
            t = 0.0 if xb - xa < 1e-9 else (x - xa) / (xb - xa)
            r = axis_y - (ya + (yb - ya) * t)
            out.append(max(r, 0.0))
        return out

    # Walk elementary intervals; the outer envelope of each interval is a
    # straight line between its boundary radii. A radius jump between
    # consecutive intervals is a drawn vertical shoulder; inside an interval
    # the covering set is constant so the envelope cannot jump.
    intervals: list[tuple[float, float, list]] = []   # (a, b, covering set)
    for a, b in zip(bps, bps[1:]):
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2.0
        covering = [ln for ln in lines if ln[0] - r_tol < mid < ln[1] + r_tol]
        if not covering:
            return [], None  # gap in the outline → not a simple revolution body
        intervals.append((a, b, covering))

    # Trim leading/trailing intervals covered only by ink that demonstrably
    # continues into the body BELOW its outer envelope (scan tails).
    # A body of revolution terminates at an end face; in rotated scans the
    # sheet rotation shears co-drawn strokes apart, so an inner bore wall may
    # protrude ~1-2 mm past the detected outer outline. Such tails cannot be
    # part of the outline and are excluded. Two safeguards keep this honest:
    #   * every covering line of a trimmed prefix must ENTER the anchor
    #     interval and sit strictly below the anchor's envelope there
    #     (an outer surface line never qualifies — it ends at its shoulder);
    #   * at most ``max_tail`` per side, and never the whole part, is dropped.
    max_tail = 2.0  # mm — rotation shear displaces co-drawn strokes by far less

    def _r_at(ln, x: float) -> float:
        xa, xb, ya, yb = ln
        t = 0.0 if xb - xa < 1e-9 else (x - xa) / (xb - xa)
        return axis_y - (ya + (yb - ya) * t)

    def _trim(side: str) -> None:
        """Drop end intervals whose every covering line continues into the
        body but stays below the local outer envelope there — image (scan)
        tails of inner bore walls. Never trims an outer-surface line run,
        never more than ``max_tail`` per side."""
        trimmed = 0.0
        while len(intervals) >= 2:
            iv = intervals[0] if side == "left" else intervals[-1]
            a, b, covering = iv
            if not covering:
                return
            for ln in covering:
                if side == "left":
                    if ln[1] <= b + r_tol:
                        return  # line ends here — it terminates a surface, keep
                else:
                    if ln[0] >= a - r_tol:
                        return
                found_underneath = False
                for a2, b2, cov2 in intervals:
                    if side == "left":
                        if b2 <= b or ln[1] <= a2 + r_tol:
                            continue
                    else:
                        if a2 >= a or ln[0] >= b2 - r_tol:
                            continue
                    amid2 = (a2 + b2) / 2.0
                    e2 = max(_radii_at(amid2, cov2))
                    if e2 - _r_at(ln, amid2) > r_tol:
                        found_underneath = True
                        break
                if not found_underneath:
                    return  # the ink is the outer surface or ends in the body
            new_trimmed = trimmed + (b - a)
            if new_trimmed > max_tail:
                return
            trimmed = new_trimmed
            intervals.pop(0 if side == "left" else -1)

    _trim("left")
    _trim("right")
    if not intervals:
        return [], None

    # Bore bookkeeping on the trimmed body. The bore wall must be ONE
    # constant full-length inner surface: intersect the per-interval inner
    # candidate radii. Shoulder-corner carry-over (the Ø40 surface still
    # visible inside the Ø60 section for a fraction of a mm) is not a wall —
    # it cannot be full-length and constant like a true bore wall. No
    # full-length constant candidate → the part is solid or the bore is
    # unresolved; no bore is reported.
    candidates: list[float] | None = None
    ok = True
    for a, b, covering in intervals:
        mid = (a + b) / 2.0
        radii = _radii_at(mid, covering)
        outer = max(radii)
        inner = [r for r in radii if outer - r > r_tol]
        if not inner:
            ok = False
            break
        if candidates is None:
            candidates = list(inner)
        else:
            candidates = [c for c in candidates
                          if any(abs(c - o) <= max(abs(o), 1.0) * 0.01 + r_tol
                                 for o in inner)]
    bore_diameter: float | None = None
    if ok and candidates:
        bore_diameter = 2.0 * candidates[0]

    def _outer_bound(a: float, b: float, covering) -> tuple[float, float]:
        ra_list = _radii_at(a, covering)
        rb_list = _radii_at(b, covering)
        return max(ra_list), max(rb_list)

    profile: list[ProfilePoint] = [ProfilePoint(intervals[0][0], 0.0)]
    prev_r: float | None = None
    for a, b, covering in intervals:
        ra, rb = _outer_bound(a, b, covering)
        if prev_r is None:
            profile.append(ProfilePoint(a, ra))
        elif abs(ra - prev_r) > r_tol:
            # vertical shoulder at a
            profile.append(ProfilePoint(a, prev_r))
            profile.append(ProfilePoint(a, ra))
        profile.append(ProfilePoint(b, rb))
        prev_r = rb
    profile.append(ProfilePoint(intervals[-1][1], 0.0))
    return _dedupe(profile), bore_diameter


def _dedupe(points: list[ProfilePoint]) -> list[ProfilePoint]:
    out: list[ProfilePoint] = []
    for p in points:
        if out and math.isclose(out[-1].x, p.x, abs_tol=1e-6) and math.isclose(out[-1].r, p.r, abs_tol=1e-6):
            continue
        out.append(p)
    return out




def extract_revolution(
    elements: list[VectorElement],
) -> tuple[list[ProfilePoint], float | None, str | None, float | None]:
    """Locate the axis and return (profile, bore_diameter, orientation, axis_coord).

    orientation is "horizontal" or "vertical"; axis_coord is the sheet position
    of the axis in mm (Y for horizontal, X for vertical). All ``None``/[] when
    there is no usable axis or the outline is not a simple body of revolution.
    """
    orientation, coord = find_axis(elements)
    if coord is None:
        return [], None, None, None
    if orientation == "vertical":
        geometry = transpose_elements(elements)
        axis_y = coord
    else:
        geometry, axis_y = elements, coord
    profile, bore = build_half_profile(geometry, axis_y)
    return profile, bore, orientation, coord
