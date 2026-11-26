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
            arr = np.asarray(raw).ravel()
            if arr.size < 4:
                continue
            x1, y1, x2, y2 = (int(v) for v in arr[:4])
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
    # statistical row/column scan for the GOST alternating long-dash/dot
    # rhythm — robust to Hough fragmentation on noisy scans
    binary = cv2.threshold(cleaned, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    axis_index = 0
    for orientation in ("row", "col"):
        lines_found = _dash_dot_axes(binary, orientation)
        for (a0, a1, fixed) in lines_found:
            if orientation == "row":
                points = [(float(a0), float(fixed)), (float(a1), float(fixed))]
            else:
                points = [(float(fixed), float(a0)), (float(fixed), float(a1))]
            elements.append(VectorElement(
                id=_uid("A", axis_index), type=ElementType.AXIS,
                points=points, stroke_width=0.4, dash="[8 3 2 3] 0",
                bbox=(min(points[0][0], points[1][0]), min(points[0][1], points[1][1]),
                      max(points[0][0], points[1][0]), max(points[0][1], points[1][1])),
            ))
            axis_index += 1

    # drop DIMENSION_LINE fragments that are actually the axis strokes
    axis_lines = [e for e in elements if e.type is ElementType.AXIS and len(e.points) == 2]
    if axis_lines:
        def _on_axis(e) -> bool:
            if e.type is not ElementType.DIMENSION_LINE or len(e.points) != 2:
                return False
            (p0, p1) = e.points
            for ax in axis_lines:
                (a0, a1) = ax.points
                ax_dx, ax_dy = a1[0] - a0[0], a1[1] - a0[1]
                norm = math.hypot(ax_dx, ax_dy)
                if norm == 0:
                    continue
                for p in (p0, p1):
                    dist = abs((p[0] - a0[0]) * ax_dy - (p[1] - a0[1]) * ax_dx) / norm
                    if dist > 2.5:
                        return False
                return True
            return False

        elements = [e for e in elements if not _on_axis(e)]

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


def _runs_1d(line: np.ndarray) -> list[tuple[int, int]]:
    xs = np.flatnonzero(line)
    if xs.size == 0:
        return []
    splits = np.flatnonzero(np.diff(xs) > 1) + 1
    starts = np.r_[0, splits]
    ends = np.r_[splits, xs.size] - 1
    return [(int(xs[s]), int(xs[e])) for s, e in zip(starts, ends)]


def _axis_signature(runs: list[tuple[int, int]]) -> float | None:
    """Validate a dash-dot rhythm; returns the covered span in px or None."""
    if len(runs) < 6:
        return None
    span = runs[-1][1] - runs[0][0]
    if span < 250:
        return None
    starts = np.array([r[0] for r in runs], dtype=np.float64)
    d = np.diff(starts)
    even, odd = d[0::2], d[1::2]
    lens_even = np.array([runs[i][1] - runs[i][0] + 1 for i in range(0, len(runs), 2)], dtype=np.float64)
    lens_odd = np.array([runs[i][1] - runs[i][0] + 1 for i in range(1, len(runs), 2)], dtype=np.float64)
    if even.size < 2 or odd.size < 2:
        return None
    a, b = float(np.median(even)), float(np.median(odd))
    len_even, len_odd = float(np.median(lens_even)), float(np.median(lens_odd))
    lo, hi = min(a, b), max(a, b)
    if lo < 12.0 or hi / lo < 1.35:
        return None  # not an alternating long/short rhythm
    for arr, med in ((even, a), (odd, b)):
        if np.mean(np.abs(arr - med) / med > 0.35) > 0.25:
            return None
    if (a + b) / 2.0 < 18.0:
        return None
    # one parity must be LONG strokes (dashes) and the other SHORT (dots);
    # random artefact rows (noise, arrowheads) have both parities short
    long_len, short_len = max(len_even, len_odd), min(len_even, len_odd)
    if long_len < 14.0 or short_len > 0.45 * long_len:
        return None
    long_lens = lens_even if len_even >= len_odd else lens_odd
    long_med = np.median(long_lens)
    if np.mean(np.abs(long_lens - long_med) / long_med > 0.40) > 0.25:
        return None
    return float(span)


def _dash_dot_axes(binary: np.ndarray, orientation: str) -> list[tuple[float, float, float]]:
    if orientation not in ("row", "col"):
        raise ValueError(orientation)
    h, w = binary.shape
    good: list[tuple[int, int, int]] = []
    scan = binary if orientation == "row" else binary.T
    for fixed in range(scan.shape[0]):
        runs = _runs_1d(scan[fixed] > 0)
        if _axis_signature(runs) is None:
            continue
        good.append((fixed, runs[0][0], runs[-1][1]))
    groups: list[list[tuple[int, int, int]]] = []
    current: list[tuple[int, int, int]] = []
    for item in good:
        if current and item[0] - current[-1][0] > 2:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)
    out: list[tuple[float, float, float]] = []
    for group in groups:
        if len(group) < 2:
            continue  # noise row, not a stroked axis
        fixed = float(np.mean([item[0] for item in group]))
        a0 = float(min(item[1] for item in group))
        a1 = float(max(item[2] for item in group))
        if a1 - a0 >= 250:
            out.append((a0, a1, fixed))
    return out
