"""Parse a vector PDF (exported from KOMPAS / CAD) into a :class:`Drawing`.

Strategy
--------
1. ``page.get_drawings()`` gives every stroked path with its line width and
   dash pattern — enough to distinguish GOST main lines (thick, solid) from
   thin dimension lines and dash-dot axis lines.
2. ``page.get_text("words")`` gives every text word with its bounding box —
   real text, not pixels, so no OCR is needed for vector PDFs.
3. Filled paths (dimension-line arrowheads, hatching fills) carry no stroke
   geometry and are ignored.

All sheet coordinates are converted from PDF points to millimetres
(1 mm = 72/25.4 pt) before being returned.

Scanned raster PDFs are out of scope here — use ``scan_preprocess`` +
``vectorize`` for those (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import fitz  # PyMuPDF

from core.models import Drawing, ElementType, ProfilePoint, VectorElement
from core.vectorize import classify_dash

PT_PER_MM = 72.0 / 25.4
MM_PER_PT = 25.4 / 72.0

# stroke-width thresholds in points (GOST: main line 0.5–1.4 mm, thin lines ≤ 0.4 mm)
_CONTOUR_MIN_WIDTH_PT = 1.2
_EPS = 1e-6


def _uid(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def _line_element(eid: str, p1, p2, width: float, dash: str | None) -> VectorElement:
    x0, y0 = p1.x * MM_PER_PT, p1.y * MM_PER_PT
    x1, y1 = p2.x * MM_PER_PT, p2.y * MM_PER_PT
    etype = _classify_stroke(width, dash, (x0, y0, x1, y1))
    return VectorElement(
        id=eid, type=etype,
        points=[(x0, y0), (x1, y1)],
        stroke_width=width * MM_PER_PT, dash=dash,
        bbox=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
    )


def _classify_stroke(width_pt: float, dash: str | None, bbox) -> ElementType:
    if classify_dash(dash):
        # dashed/dash-dot lines: candidates for the axis (GOST dash-dot)
        x0, y0, x1, y1 = bbox
        if abs(y1 - y0) <= 1.0:  # horizontal dash-dot → axis
            return ElementType.AXIS
        return ElementType.UNKNOWN
    if width_pt >= _CONTOUR_MIN_WIDTH_PT:
        return ElementType.CONTOUR
    return ElementType.DIMENSION_LINE


def _text_elements(page: fitz.Page, start_index: int) -> list[VectorElement]:
    elements: list[VectorElement] = []
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    for i, w in enumerate(words):
        x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
        text = word.strip()
        if not text:
            continue
        elements.append(VectorElement(
            id=_uid("T", start_index + i),
            type=ElementType.TEXT,
            points=[((x0 + x1) / 2 * MM_PER_PT, (y0 + y1) / 2 * MM_PER_PT)],
            text=text,
            bbox=(x0 * MM_PER_PT, y0 * MM_PER_PT, x1 * MM_PER_PT, y1 * MM_PER_PT),
        ))
    return elements


def _find_axis_y(elements: list[VectorElement], page_height_mm: float) -> float | None:
    """The axis of a body of revolution is the longest horizontal AXIS element."""
    axis_lines = [e for e in elements if e.type == ElementType.AXIS
                  and len(e.points) == 2
                  and abs(e.points[0][1] - e.points[1][1]) < 0.5]
    if not axis_lines:
        return None
    best = max(axis_lines, key=lambda e: abs(e.points[1][0] - e.points[0][0]))
    return (best.points[0][1] + best.points[1][1]) / 2.0


def _build_profile(elements: list[VectorElement], axis_y: float) -> list[ProfilePoint]:
    """Reconstruct the half-profile (x, r) of a stepped body of revolution.

    Uses only strictly-horizontal CONTOUR segments above the axis. The outline
    of a GOST half-section is a step function in x; each horizontal segment is
    one cylindrical surface with radius ``axis_y - y``. Works for shafts,
    flanges, bushings and rings; anything else yields an empty profile.
    """
    segments: list[tuple[float, float, float]] = []
    for e in elements:
        if e.type != ElementType.CONTOUR or len(e.points) != 2:
            continue
        (x0, y0), (x1, y1) = e.points
        if abs(y1 - y0) > 0.05:          # keep horizontal only
            continue
        y = (y0 + y1) / 2.0
        if y >= axis_y - 0.05:           # keep only the upper half
            continue
        xa, xb = sorted((x0, x1))
        segments.append((xa, xb, axis_y - y))

    if not segments:
        return []

    # Split the x-range at every breakpoint; each elementary interval must be
    # covered by exactly one surface segment — otherwise this is not a simple
    # body of revolution and we return an empty profile rather than guess.
    breakpoints = sorted({x for xa, xb, _ in segments for x in (xa, xb)})
    if len(breakpoints) < 2:
        return []

    r_tol = 0.01  # mm
    intervals: list[tuple[float, float, float]] = []
    for a, b in zip(breakpoints, breakpoints[1:]):
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2.0
        covering = [r for xa, xb, r in segments if xa - r_tol < mid < xb + r_tol]
        if not covering:
            return []  # gap in the outline → not a simple revolution body
        # concentric duplicate surfaces (top/bottom both fed this far) share r;
        # conflicting radii at the same x cannot be resolved — refuse to guess.
        if max(covering) - min(covering) > r_tol:
            return []
        intervals.append((a, b, covering[0]))

    x_min, x_max = breakpoints[0], breakpoints[-1]
    profile: list[ProfilePoint] = [ProfilePoint(x_min, 0.0), ProfilePoint(x_min, intervals[0][2])]
    prev_r = intervals[0][2]
    for a, b, r in intervals:
        if abs(r - prev_r) > r_tol:
            # vertical shoulder at x == a
            profile.append(ProfilePoint(a, prev_r))
            profile.append(ProfilePoint(a, r))
            prev_r = r
        profile.append(ProfilePoint(b, r))
    profile.append(ProfilePoint(x_max, 0.0))
    return _dedupe(profile)


def _dedupe(points: list[ProfilePoint]) -> list[ProfilePoint]:
    out: list[ProfilePoint] = []
    for p in points:
        if out and math.isclose(out[-1].x, p.x, abs_tol=1e-6) and math.isclose(out[-1].r, p.r, abs_tol=1e-6):
            continue
        out.append(p)
    return out


def parse_pdf(path: str | Path) -> Drawing:
    """Parse a vector PDF and return a :class:`Drawing`.

    Raises :class:`FileNotFoundError` if the file does not exist and
    :class:`ValueError` for a non-PDF or empty document.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Drawing not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"parse_pdf expects a .pdf file, got: {path.suffix}")

    doc = fitz.open(path)
    if doc.page_count == 0:
        doc.close()
        raise ValueError(f"Empty PDF: {path}")

    page = doc.load_page(0)
    page_rect = page.rect
    elements: list[VectorElement] = []
    n = 0

    for drawing in page.get_drawings():
        width = drawing.get("width") or 0.0
        dashes = (drawing.get("dashes") or "").strip()
        dash = None if dashes in ("", "[] 0") else dashes
        if drawing.get("fill") is not None and drawing.get("color") is None:
            continue  # filled arrowhead / hatch fill — no stroked geometry
        for item in drawing.get("items", []):
            if item[0] == "l":  # line segment
                elements.append(_line_element(_uid("L", n), item[1], item[2], width, dash))
                n += 1
            elif item[0] == "re":  # rectangle
                r = item[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
                for a, b in zip(pts, pts[1:]):
                    elements.append(_line_element(_uid("L", n), a, b, width, dash))
                    n += 1
            # curves (c/qu) are ignored in v1 — see docs/ROADMAP.md (fillets as arcs)

    elements.extend(_text_elements(page, n))

    page_width_mm = page_rect.width * MM_PER_PT
    page_height_mm = page_rect.height * MM_PER_PT
    axis_y = _find_axis_y(elements, page_height_mm)
    profile = _build_profile(elements, axis_y) if axis_y is not None else []

    from core.models import View
    drawing_obj = Drawing(
        source_path=str(path),
        page_width=page_width_mm,
        page_height=page_height_mm,
        elements=elements,
        profile=profile,
    )
    drawing_obj.views = [View(
        name="main",
        bbox=(0.0, 0.0, page_width_mm, page_height_mm),
        elements=elements,
        axis_y=axis_y,
    )]
    doc.close()
    return drawing_obj
