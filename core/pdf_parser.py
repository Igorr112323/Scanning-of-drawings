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
from pathlib import Path

import fitz  # PyMuPDF

from core.models import Drawing, ElementType, ProfilePoint, VectorElement
from core.geometry import extract_revolution
from core.vectorize import classify_dash

PT_PER_MM = 72.0 / 25.4
MM_PER_PT = 25.4 / 72.0

# stroke-width thresholds in points (GOST: main line 0.5–1.4 mm, thin lines ≤ 0.4 mm)
_CONTOUR_MIN_WIDTH_PT = 1.2


def _uid(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def _pt_xy(p) -> tuple[float, float]:
    """Accept fitz.Point / quad-like / plain (x, y) tuple."""
    if isinstance(p, tuple):
        return float(p[0]), float(p[1])
    return float(p.x), float(p.y)


def _line_element(eid: str, p1, p2, width: float, dash: str | None) -> VectorElement:
    x0, y0 = _pt_xy(p1)
    x1, y1 = _pt_xy(p2)
    x0, y0, x1, y1 = x0 * MM_PER_PT, y0 * MM_PER_PT, x1 * MM_PER_PT, y1 * MM_PER_PT
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
        if abs(y1 - y0) <= 1.0 or abs(x1 - x0) <= 1.0:  # horizontal/vertical dash-dot → axis
            return ElementType.AXIS
        return ElementType.UNKNOWN
    if width_pt >= _CONTOUR_MIN_WIDTH_PT:
        return ElementType.CONTOUR
    return ElementType.DIMENSION_LINE


def _pt_dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) if isinstance(a, tuple) else math.hypot(a.x - b.x, a.y - b.y)


def _dist_point_chord(p, a, b) -> float:
    """Distance of point p from the chord a–b (all in sheet coordinates)."""
    ax, ay = (a[0], a[1]) if isinstance(a, tuple) else (a.x, a.y)
    bx, by = (b[0], b[1]) if isinstance(b, tuple) else (b.x, b.y)
    px, py = (p[0], p[1]) if isinstance(p, tuple) else (p.x, p.y)
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    return abs(dy * px - dx * py + bx * ay - by * ax) / math.hypot(dx, dy)


def _cubic_chords(p0, c1, c2, p3, tol_pt: float = 0.3, max_depth: int = 12) -> list:
    """Adaptive de Casteljau flattening of a cubic Bezier.

    Auto-traced GOST outlines carry fillet/chamfer arcs as curves; ignoring
    them leaves coverage gaps in the half-profile. Flatten to chords whose
    sagitta stays below ``tol_pt`` (≈0.1 mm)."""
    out: list = []

    def rec(a, b, c, d, depth: int) -> None:
        if depth >= max_depth or (
            _dist_point_chord(b, a, d) <= tol_pt and _dist_point_chord(c, a, d) <= tol_pt
        ):
            out.append(d)
            return
        m01 = _mid(a, b); m12 = _mid(b, c); m23 = _mid(c, d)
        m012 = _mid(m01, m12); m123 = _mid(m12, m23)
        m0123 = _mid(m012, m123)
        rec(a, m01, m012, m0123, depth + 1)
        rec(m0123, m123, m23, d, depth + 1)

    def _mid(a, b):
        if isinstance(a, tuple):
            return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        return fitz.Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)

    rec(p0, c1, c2, p3, 0)
    return out


def _quad_chords(p0, cc, p2, tol_pt: float = 0.3, max_depth: int = 12) -> list:
    """Adaptive flattening of a quadratic Bezier (fitz 'qu' items)."""
    out: list = []

    def rec(a, c, b, depth: int) -> None:
        if depth >= max_depth or _dist_point_chord(c, a, b) <= tol_pt:
            out.append(b)
            return
        m01 = _mid(a, c); m12 = _mid(c, b)
        m012 = _mid(m01, m12)
        rec(a, m01, m012, depth + 1)
        rec(m012, m12, b, depth + 1)

    def _mid(a, c):
        if isinstance(a, tuple):
            return ((a[0] + c[0]) / 2.0, (a[1] + c[1]) / 2.0)
        return fitz.Point((a.x + c.x) / 2.0, (a.y + c.y) / 2.0)

    rec(p0, cc, p2, 0)
    return out


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
            elif item[0] in ("c", "qu"):
                # flatten Bezier/arcs to chords — GOST traced outlines draw
                # fillets as curves; ignoring them broke outline coverage
                if item[0] == "c":
                    chord_pts = [item[1]] + _cubic_chords(item[1], item[2], item[3], item[4])
                else:
                    chord_pts = [item[1]] + _quad_chords(item[1], item[2], item[3])
                for a, b in zip(chord_pts, chord_pts[1:]):
                    elements.append(_line_element(_uid("L", n), a, b, width, dash))
                    n += 1

    elements.extend(_text_elements(page, n))

    page_width_mm = page_rect.width * MM_PER_PT
    page_height_mm = page_rect.height * MM_PER_PT
    profile, bore_diameter, axis_orientation, axis_coord = extract_revolution(
        elements, page_height_mm=page_height_mm)
    axis_y: float | None = axis_coord if axis_orientation == "horizontal" else None

    from core.models import View
    drawing_obj = Drawing(
        source_path=str(path),
        page_width=page_width_mm,
        page_height=page_height_mm,
        elements=elements,
        profile=profile,
        bore_diameter=bore_diameter,
    )
    drawing_obj.views = [View(
        name="main",
        bbox=(0.0, 0.0, page_width_mm, page_height_mm),
        elements=elements,
        axis_y=axis_y,
    )]
    doc.close()
    return drawing_obj
