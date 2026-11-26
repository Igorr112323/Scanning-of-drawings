"""Raster → vector classification for scanned drawings.

Basic but real implementation for v1 (see docs/ROADMAP.md — neural
segmentation is explicitly out of scope until a labeled dataset exists):

    preprocess_scan(image)  →  binarized, deskewed image
    vectorize(cleaned)      →  list[VectorElement]

Vector elements are recovered with Hough line detection and grouped into
GOST-style classes:

    CONTOUR        thick, solid strokes (main lines)
    DIMENSION_LINE thin, solid strokes (dimensions, extension lines, leaders)
    AXIS           dash-dot centre lines of bodies of revolution
    HATCH          short thin strokes at ~45° (section hatching)
    TEXT           text candidates are NOT produced here — use OCR on the
                   cleaned image (core.ocr_gost) for raster input

Dash-dot grouping: thin collinear strokes whose gaps follow a regular
long–short pattern are merged into one AXIS candidate. Anything ambiguous is
returned as UNKNOWN — we never guess a class silently; downstream stages
treat UNKNOWN as non-geometry.
"""

from __future__ import annotations

import math
import re

import cv2
import numpy as np

from core.models import ElementType, VectorElement

_DASH_RE = re.compile(r"\[\s*([0-9.\s]*)\s*\]\s*([0-9.]+)?")


def classify_dash(dash: str | None) -> bool:
    """Return True if a PDF dash-pattern string denotes a dashed line."""
    if not dash:
        return False
    m = _DASH_RE.match(dash.strip())
    if not m:
        return False
    parts = [float(p) for p in m.group(1).split()]
    return any(p > 0 for p in parts)


def _uid(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def vectorize(cleaned: np.ndarray) -> list[VectorElement]:
    """Classify primitives in a binarized scan into vector elements.

    ``cleaned`` is a single-channel image from :func:`core.scan_preprocess.preprocess_scan`
    (white background, dark strokes). Pixel coordinates are returned as-is;
    callers that need millimetres must apply the scan DPI separately.
    """
    if cleaned is None or cleaned.size == 0:
        raise ValueError("vectorize() got an empty image")
    if cleaned.ndim == 3:
        cleaned = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)

    _, binary = cv2.threshold(cleaned, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    elements: list[VectorElement] = []

    # --- line primitives -------------------------------------------------
    edges = cv2.Canny(binary, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180,
                            threshold=40, minLineLength=25, maxLineGap=12)

    line_index = 0
    if lines is not None:
        for raw in lines:
            x1, y1, x2, y2 = (int(v) for v in raw[0])
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 1:
                continue
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
            # stroke thickness: probe perpendicular samples of the binary image
            thickness = _stroke_thickness(binary, x1, y1, x2, y2)
            if thickness >= 2.4:
                etype = ElementType.CONTOUR
            elif abs(angle - 45.0) < 8.0 or abs(angle - 135.0) < 8.0:
                etype = ElementType.HATCH if length < 30 else ElementType.CONTOUR
            else:
                etype = ElementType.DIMENSION_LINE
            elements.append(VectorElement(
                id=_uid("L", line_index), type=etype,
                points=[(float(x1), float(y1)), (float(x2), float(y2))],
                stroke_width=float(thickness),
                bbox=(float(min(x1, x2)), float(min(y1, y2)),
                      float(max(x1, x2)), float(max(y1, y2))),
            ))
            line_index += 1

    # --- dash-dot axis candidates -----------------------------------------
    # thin horizontal strokes in regular groups are GOST centre lines
    rows: dict[int, list[int]] = {}
    for i, e in enumerate(elements):
        if e.type is not ElementType.DIMENSION_LINE:
            continue
        p0, p1 = e.points
        if abs(p0[1] - p1[1]) > 1.0:
            continue
        rows.setdefault(round((p0[1] + p1[1]) / 2.0 / 8.0), []).append(i)
    consumed: set[int] = set()
    axis_index = 0
    for _, idxs in rows.items():
        xs = sorted(
            (min(elements[i].points[0][0], elements[i].points[1][0]),
             max(elements[i].points[0][0], elements[i].points[1][0]))
            for i in idxs
        )
        gaps = [xs[i + 1][0] - xs[i][1] for i in range(len(xs) - 1)]
        regular = bool(gaps) and max(gaps) - min(gaps) < 6.0 and all(g > 1.5 for g in gaps)
        span = max(x1 for _, x1 in xs) - min(x0 for x0, _ in xs)
        if regular and span > 150 and len(xs) >= 4:
            axis_y = float(np.mean([(elements[i].points[0][1] + elements[i].points[1][1]) / 2.0 for i in idxs]))
            x0 = float(min(x for x, _ in xs)); x1 = float(max(x for _, x in xs))
            elements.append(VectorElement(
                id=_uid("A", axis_index), type=ElementType.AXIS,
                points=[(x0, axis_y), (x1, axis_y)],
                stroke_width=0.4, dash="[8 3 2 3] 0",
                bbox=(x0, axis_y - 1, x1, axis_y + 1),
            ))
            axis_index += 1
            consumed.update(idxs)
    if consumed:
        elements = [e for i, e in enumerate(elements) if i not in consumed]

    return elements


def _stroke_thickness(binary: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    """Estimate stroke width by walking the perpendicular of a stroke."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    nx, ny = -dy / length, dx / length
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    h, w = binary.shape[:2]
    count = 0
    for t in range(-6, 7):
        x = int(round(cx + nx * t)); y = int(round(cy + ny * t))
        if 0 <= x < w and 0 <= y < h and binary[y, x] > 0:
            count += 1
    return float(max(1, count))
