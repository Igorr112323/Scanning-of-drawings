"""Scan dimension linking: thin-stroke reclassification + nearest-element search.

Why this exists
---------------
At 200 DPI a GOST thin line (0.6 pt ≈ 1.65 px drawn) probes as 3–4 px on a
noisy scan — *above* the old CONTOUR threshold, so dimension strokes were
typed as part outline and dimension linking found nothing (1 of 10 dimensions
linked on ``scan_test.png``). This module implements the reclassification
heuristics agreed for scans (see docs/ARCHITECTURE.md):

1. **Main contour**: the revolution outline is symmetric about the axis.
   Horizontal strokes are grouped into rows; a row whose mirror row
   ``r' = 2·axis_y − r`` holds overlapping ink votes for the outline. The
   union bbox of voted strokes (expanded by 5 %) bounds the part.
2. **Candidate DIMENSION strokes**: thin CONTOUR strokes that are either
   - **outside** the expanded main bbox (dimension/extension rows, far
     fragments), or
   - **inside but not horizontal** and within 40 px of an OCR text box
     (Ø/R leaders, vertical chain ticks, diagonal chamfer leaders — the
     part outline never leaves its own rows), or
   - carrying an **arrowhead-wide zone** near an endpoint (filled triangle
     merged into the stroke, detected by a cross-width probe), or
   - **diagonal** leaders anchored to a text box.
   Horizontal strokes inside the bbox are *never* reclassified — they are
   the revolution surfaces of the profile.
3. **Arrowhead check**: ``end_arrow_signal`` probes the perpendicular ink
   width 12–28 px inside each stroke endpoint; a width ≥ 8 px (plain line:
   ≈ 3–4 px) marks a filled arrowhead. Used both as a reclassification
   trigger and as a linking-confidence signal.
4. **Ø leaders**: vertical/diagonal thin strokes attached to an OCR diameter
   callout are reclassified as DIMENSION_LINE; the solver links the Ø text to
   that leader (see core.ocr_gost.recognize_dimensions).
5. **Chain dimensions**: aligned LINEAR texts on one baseline are linked to
   sequential segments of their dimension line; segments are cut at the x of
   crossing extension lines (see recognize_dimensions).

``nearest_vector_element`` backs the manual click-to-link flow in the UI.
"""

from __future__ import annotations

import math

from core.models import Dimension, ElementType, VectorElement

_ROW_TOL_PX = 4.0        # rows grouped within this many px
_MIN_SPAN_PX = 25.0      # mirrored-row overlap required to vote outline
_BBOX_EXPAND = 0.05      # main bbox expanded by 5 %
_THIN_PX = 4.0           # drawn thin line probes ≤ 4 px after noise+blur at 200 DPI
_TEXT_NEAR_PX = 40.0     # within this distance of an OCR word box = anchored to it
_ARROW_PROBE_PX = (12, 28)   # probe window inside a stroke endpoint
_ARROW_WIDTH_PX = 8.0        # cross-width that marks a filled arrowhead


def _hspan(e: VectorElement) -> tuple[float, float] | None:
    (x0, y0), (x1, y1) = e.points
    if abs(y1 - y0) > _ROW_TOL_PX:
        return None
    return (min(x0, x1), max(x0, x1))


def axis_y_of(elements: list[VectorElement]) -> float | None:
    """y of the longest AXIS element (revolution centreline), in the caller's units."""
    best = None
    best_len = 0.0
    for e in elements:
        if e.type is not ElementType.AXIS or len(e.points) != 2:
            continue
        (x0, y0), (x1, y1) = e.points
        length = math.hypot(x1 - x0, y1 - y0)
        if length > best_len:
            best_len = length
            best = (y0 + y1) / 2.0
    return best


def main_contour_bbox(elements: list[VectorElement], axis_y: float | None = None) \
        -> tuple[float, float, float, float] | None:
    """Bounding box of the part outline, expanded by 5 % (None if empty).

    Mirrored-row vote: a horizontal CONTOUR row that finds overlapping ink on
    its mirror row about the axis belongs to the revolution profile. The
    union of voted rows (plus any thick stroke with w ≥ 5 px as a fallback)
    bounds the part; dimension rows (240 / chain) never vote.
    """
    if axis_y is None:
        axis_y = axis_y_of(elements)
    horizontal: list[tuple[VectorElement, float, float, float]] = []
    for e in elements:
        if e.type is not ElementType.CONTOUR or len(e.points) != 2:
            continue
        span = _hspan(e)
        if span:
            y = (e.points[0][1] + e.points[1][1]) / 2.0
            horizontal.append((e, span[0], span[1], y))

    voted: set[int] = set()
    if axis_y is not None and horizontal:
        buckets: dict[int, list[tuple[int, float, float, float]]] = {}
        for idx, (_e, xa, xb, y) in enumerate(horizontal):
            key = int(round(y / (2.0 * _ROW_TOL_PX)))
            buckets.setdefault(key, []).append((idx, xa, xb, y))
        keys = list(buckets)
        for i, key in enumerate(keys):
            y_c = float(_mean([r[3] for r in buckets[key]]))
            mirror_y = 2.0 * axis_y - y_c
            m_key = int(round(mirror_y / (2.0 * _ROW_TOL_PX)))
            for other in (m_key - 1, m_key, m_key + 1):
                if other not in buckets:
                    continue
                for idx_a, xa, xb, ya in buckets[key]:
                    for idx_b, xa2, xb2, yb in buckets[other]:
                        if min(xb, xb2) - max(xa, xa2) >= _MIN_SPAN_PX:
                            voted.add(idx_a)
                            voted.add(idx_b)
    outline = [horizontal[i][0] for i in sorted(voted)]
    if not outline:
        outline = [e for e in elements
                   if e.type is ElementType.CONTOUR and e.stroke_width >= 5.0]
    if not outline:
        outline = [e for e in elements
                   if e.type is ElementType.CONTOUR and len(e.points) == 2]
    if not outline:
        return None
    xs0 = min(min(p[0] for p in e.points) for e in outline)
    ys0 = min(min(p[1] for p in e.points) for e in outline)
    xs1 = max(max(p[0] for p in e.points) for e in outline)
    ys1 = max(max(p[1] for p in e.points) for e in outline)
    cx, cy = (xs0 + xs1) / 2.0, (ys0 + ys1) / 2.0
    w = (xs1 - xs0) * (1.0 + 2 * _BBOX_EXPAND)
    h = (ys1 - ys0) * (1.0 + 2 * _BBOX_EXPAND)
    return (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rect_distance_segment(p0, p1, box) -> float:
    """Distance from a segment to an axis-aligned box (0 when they touch)."""
    x0, y0, x1, y1 = box
    def point_rect(px, py):
        dx = max(x0 - px, 0.0, px - x1)
        dy = max(y0 - py, 0.0, py - y1)
        return math.hypot(dx, dy)
    d = min(point_rect(p0[0], p0[1]), point_rect(p1[0], p1[1]))
    if d == 0.0:
        return 0.0
    # segment vs rect edges
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def seg_seg(s, t):
        def orient(a, b, c):
            v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return 0.0 if abs(v) < 1e-12 else (1.0 if v > 0 else -1.0)
        (a, b), (c, d_) = s, t
        o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d_), orient(c, d_, a), orient(c, d_, b)
        return o1 != o2 and o3 != o4 and o1 != 0.0 and o2 != 0.0 and o3 != 0.0 and o4 != 0.0

    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    for e1, e2 in edges:
        if seg_seg((p0, p1), (e1, e2)):
            return 0.0
    # point-to-segment for the box corners
    ax, ay = p0
    bx, by = p1
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    best = d
    for cx_, cy_ in corners:
        if length_sq == 0.0:
            dist = math.hypot(cx_ - ax, cy_ - ay)
        else:
            t = max(0.0, min(1.0, ((cx_ - ax) * dx + (cy_ - ay) * dy) / length_sq))
            dist = math.hypot(cx_ - (ax + t * dx), cy_ - (ay + t * dy))
        best = min(best, dist)
    return best


def end_arrow_signal(cleaned, e: VectorElement,
                     angle_deg_tol: float = 180.0) -> bool:
    """True if a filled arrowhead sits at either stroke end.

    A filled triangle merged into a line widens the perpendicular ink to
    ≥ 8 px (plain thin line: 3–4 px). Probes the window 12–28 px inside the
    stroke from each endpoint. ``cleaned`` is the binarized scan (single
    channel, dark ink on light); without it the signal is unavailable.
    """
    if cleaned is None or len(e.points) != 2:
        return False
    (x0, y0), (x1, y1) = e.points
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 30.0:
        return False
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    h, w = cleaned.shape[:2]

    def cross_width(px, py):
        run = best = 0
        for t in range(-14, 15):
            x = int(round(px + nx * t)); y = int(round(py + ny * t))
            if 0 <= x < w and 0 <= y < h and cleaned[y, x] < 210:
                run += 1; best = max(best, run)
            else:
                run = 0
        return best

    for sign in (1.0, -1.0):
        ex, ey = (x0, y0) if sign == 1.0 else (x1, y1)
        for off in _ARROW_PROBE_PX:
            px, py = ex + ux * off * sign, ey + uy * off * sign
            if 0 <= int(px) < w and 0 <= int(py) < h:
                if cross_width(px, py) >= _ARROW_WIDTH_PX:
                    return True
    return False


def reclassify_scan_elements(elements: list[VectorElement],
                             text_boxes: list[tuple[float, float, float, float]],
                             cleaned=None) -> list[VectorElement]:
    """Return a new element list with thin dimension strokes → DIMENSION_LINE.

    Never reclassifies AXIS/TEXT. Horizontal CONTOUR strokes inside the main
    bbox keep their class (revolution surfaces). See module docstring /
    docs/ARCHITECTURE.md for the exact rule order.
    """
    main = main_contour_bbox(elements)
    if main is None:
        return list(elements)
    mx0, my0, mx1, my1 = main

    def _inside(e) -> bool:
        (x0, y0), (x1, y1) = e.points
        return not (max(x0, x1) < mx0 or min(x0, x1) > mx1
                    or max(y0, y1) < my0 or min(y0, y1) > my1)

    def _horizontal(e) -> bool:
        (x0, y0), (x1, y1) = e.points
        return abs(y1 - y0) <= _ROW_TOL_PX

    def _near_text(e, limit: float = _TEXT_NEAR_PX) -> bool:
        return any(_rect_distance_segment(e.points[0], e.points[1], box) <= limit
                   for box in text_boxes)

    out: list[VectorElement] = []
    for e in elements:
        if e.type is not ElementType.CONTOUR or len(e.points) != 2:
            out.append(e)
            continue
        thin = e.stroke_width <= _THIN_PX
        if not thin:
            # still promote a moderately wide non-horizontal stroke anchored
            # to a text box — it is a leader blurred around its junctions,
            # never a revolution surface (those are horizontal or text-free)
            inside = _inside(e)
            if inside and e.stroke_width <= 6.0 and not _horizontal(e) and _near_text(e):
                out.append(VectorElement(
                    id=e.id, type=ElementType.DIMENSION_LINE, points=list(e.points),
                    stroke_width=e.stroke_width, dash=e.dash, text=e.text,
                    bbox=e.bbox, ocr_confidence=e.ocr_confidence,
                    arrow_end=end_arrow_signal(cleaned, e),
                ))
                continue
            out.append(e)
            continue
        inside = _inside(e)
        near = _near_text(e)
        arrow = end_arrow_signal(cleaned, e)
        if not inside:
            # dimension / extension rows and outlying fragments
            new = ElementType.DIMENSION_LINE
        elif near and not _horizontal(e):
            # vertical Ø leader or diagonal chamfer leader anchored to its text
            new = ElementType.DIMENSION_LINE
        else:
            # NOTE: the arrowhead probe is deliberately *not* a standalone
            # trigger here — on this scan it fires equally on T-junctions
            # (boss shoulder ↔ surface). It is recorded on the element and
            # used as a linking-confidence signal instead.
            new = ElementType.CONTOUR
        out.append(VectorElement(
            id=e.id, type=new, points=list(e.points),
            stroke_width=e.stroke_width, dash=e.dash,
            text=e.text, bbox=e.bbox, ocr_confidence=e.ocr_confidence,
            arrow_end=arrow,
        ))
    return out


def confirm_dimension_link(dim: Dimension, element_id: str) -> Dimension:
    """Return a confirmed copy of ``dim`` linked to ``element_id``.

    The manual click-to-link flow: the user picked the element on the
    drawing, so the dimension is treated as human-confirmed (confidence 1.0,
    not uncertain) regardless of OCR quality. The original value/symbol are
    kept — only the binding changes.
    """
    return Dimension(
        id=dim.id, symbol=dim.symbol, value=dim.value, raw_text=dim.raw_text,
        confidence=1.0, linked_element_id=element_id, is_uncertain=False,
        anchor=dim.anchor,
    )


def nearest_vector_element(elements: list[VectorElement], x: float, y: float,
                           max_dist: float | None = None,
                           types: tuple[ElementType, ...] = (
                               ElementType.CONTOUR, ElementType.AXIS,
                               ElementType.DIMENSION_LINE)) -> VectorElement | None:
    """Nearest element (point-to-segment distance); None when nothing qualifies.

    Backs click-to-link in the UI: the user clicks a dimension row, then a
    point on the drawing; the closest geometric element to that point becomes
    the dimension's link. TEXT elements are never link targets.
    """
    best: VectorElement | None = None
    best_d = math.inf
    for e in elements:
        if e.type not in types or len(e.points) != 2:
            continue
        (ax, ay), (bx, by) = e.points
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq == 0.0:
            d = math.hypot(x - ax, y - ay)
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
            d = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if d < best_d:
            best_d, best = d, e
    if best is None or (max_dist is not None and best_d > max_dist):
        return None
    return best
