"""Dimension recognition: GOST/ESKD symbols, numbers, and linking to geometry.

Two entry points:

``recognize_dimensions(drawing)``
    Turns the TEXT elements already extracted by the parser (vector PDF text is
    exact — no OCR involved) into :class:`core.models.Dimension` objects and
    links each to the nearest drawing element.

``ocr_words(image)``
    Offline OCR fallback for raster scans via a local Tesseract binary
    (pytesseract). Never used for vector PDFs. If Tesseract is not installed it
    raises RuntimeError with a clear message — no network calls, no silent
    failure, no invented text.

The fundamental rule: if we cannot parse the text with high confidence or
cannot link it to a geometric element, ``is_uncertain=True`` and the UI must
make the user confirm it. We never invent a number.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from core.models import (
    CONFIDENCE_THRESHOLD,
    Dimension,
    Drawing,
    ElementType,
    Symbol,
    VectorElement,
)

# strict: "Ø50", "Ø 50.5", "⌀40", "R12", "M8x1.25", "120", "120,5"
_STRICT = re.compile(
    r"^(?P<prefix>Ø|⌀|∅|Φ|%%c|%%C|R|M)?\s*(?P<num>\d{1,4}(?:[.,]\d{1,4})?)(?:\s*[xхX×].*)?$"
)
# loose: same, but tolerate OCR confusions inside the numeric part (O/o→0, l→1, S→5)
_LOOSE_NUM = re.compile(r"^(?P<prefix>Ø|⌀|∅|Φ|%%c|%%C|R|M)?\s*(?P<num>[0-9OoIlSsB]{1,4}(?:[.,][0-9OoIlSsB]{1,4})?)(?:\s*[xхX×].*)?$")

_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})

# how far (mm) from the text anchor we still consider an element linked
_LINK_RADIUS_MM = 9.0
# beyond this distance even a clean pattern is downgraded
_FAR_LINK_MM = 5.0


def _parse_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_dimension_text(text: str) -> tuple[Symbol, float, float] | None:
    """Parse a single text word into (symbol, value, parse_confidence).

    Returns None if the text is not a dimension at all (plain annotation).
    ``parse_confidence`` is 0.95 for a strict match and ≤ 0.7 when OCR-style
    confusions had to be resolved (→ uncertain).
    """
    t = text.strip().strip(";,.")
    if not t:
        return None

    m = _STRICT.match(t)
    if m:
        num = _parse_number(m.group("num"))
        if num is None:
            return None
        return _symbol(m.group("prefix")), num, 0.95

    m = _LOOSE_NUM.match(t)
    if m:
        num_raw = m.group("num")
        fixed = num_raw.translate(_CONFUSABLE)
        num = _parse_number(fixed)
        if num is not None and any(c in "OoIlSsB" for c in num_raw):
            return _symbol(m.group("prefix")), num, 0.6
    return None


def _symbol(prefix: str | None) -> Symbol:
    if prefix in ("Ø", "⌀", "∅", "Φ", "%%c", "%%C"):
        return Symbol.DIAMETER
    if prefix == "R":
        return Symbol.RADIUS
    if prefix == "M":
        return Symbol.THREAD
    return Symbol.LINEAR


def _distance_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _distance_point_to_element(p: tuple[float, float], e: VectorElement) -> float:
    px, py = p
    best = math.inf
    if len(e.points) == 2:
        (ax, ay), (bx, by) = e.points
        best = min(best, _distance_point_to_segment(px, py, ax, ay, bx, by))
    elif e.bbox:
        x0, y0, x1, y1 = e.bbox
        cx = min(max(px, x0), x1)
        cy = min(max(py, y0), y1)
        best = min(best, math.hypot(px - cx, py - cy))
    return best


def recognize_dimensions(drawing: Drawing) -> list[Dimension]:
    """Recognize dimension texts in a parsed drawing and link them to geometry."""
    dimensions: list[Dimension] = []
    candidates = [e for e in drawing.elements
                  if e.type in (ElementType.CONTOUR, ElementType.DIMENSION_LINE, ElementType.AXIS)]

    idx = 0
    for element in drawing.elements:
        if element.type is not ElementType.TEXT or not element.text:
            continue
        parsed = parse_dimension_text(element.text)
        if parsed is None:
            # a word like "Ø5O" still starts with a diameter marker —
            # report it as uncertain rather than silently dropping it
            if _looks_like_dimension(element.text):
                dimensions.append(Dimension(
                    id=f"DIM-{idx:04d}", symbol=_guess_symbol(element.text),
                    value=0.0, raw_text=element.text, confidence=0.2,
                    linked_element_id=None, is_uncertain=True,
                    anchor=element.points[0] if element.points else None,
                ))
                idx += 1
            continue

        symbol, value, confidence = parsed
        anchor = element.points[0] if element.points else (0.0, 0.0)

        nearest_id, nearest_dist = None, math.inf
        for cand in candidates:
            d = _distance_point_to_element(anchor, cand)
            if d < nearest_dist:
                nearest_dist, nearest_id = d, cand.id

        linked = nearest_id is not None and nearest_dist <= _LINK_RADIUS_MM
        if not linked:
            confidence = min(confidence, 0.6)
        elif nearest_dist > _FAR_LINK_MM:
            confidence = min(confidence, 0.9)

        dimensions.append(Dimension(
            id=f"DIM-{idx:04d}", symbol=symbol, value=value,
            raw_text=element.text, confidence=round(confidence, 3),
            linked_element_id=nearest_id if linked else None,
            is_uncertain=confidence < CONFIDENCE_THRESHOLD,
            anchor=anchor,
        ))
        idx += 1
    return dimensions


def _looks_like_dimension(text: str) -> bool:
    t = text.strip()
    return bool(t) and (
        t[0] in "Ø⌀∅ΦRM" or t.lower().startswith("%%c")
    ) and any(ch.isdigit() for ch in t)


def _guess_symbol(text: str) -> Symbol:
    t = text.strip()
    if t and t[0] in "Ø⌀∅Φ" or t.lower().startswith("%%c"):
        return Symbol.DIAMETER
    if t.startswith("R"):
        return Symbol.RADIUS
    if t.startswith("M"):
        return Symbol.THREAD
    return Symbol.UNKNOWN


def ocr_words(image) -> list[VectorElement]:
    """Raster-OCR fallback for scanned drawings (offline, local Tesseract).

    Returns TEXT elements (same shape as the vector parser produces). Raises
    RuntimeError if pytesseract or the Tesseract binary is unavailable —
    callers must surface that to the user instead of continuing blindly.
    """
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - depends on system
        raise RuntimeError(
            "Tesseract/pytesseract is not available. Install the system "
            "'tesseract-ocr' package and 'pip install pytesseract' to use "
            "OCR on scans. Vector PDFs do not need OCR."
        ) from exc

    config = "--psm 6 -c tessedit_char_whitelist=0123456789Ø⌀RMrm.,x× "
    try:
        data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
    except Exception as exc:  # pragma: no cover - depends on system
        raise RuntimeError(f"Tesseract OCR failed: {exc}") from exc

    elements: list[VectorElement] = []
    n = 0
    for i in range(len(data["text"])):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        try:
            x, y = float(data["left"][i]), float(data["top"][i])
            w, h = float(data["width"][i]), float(data["height"][i])
            conf = float(data["conf"][i])
        except (ValueError, KeyError):
            continue
        elements.append(VectorElement(
            id=f"T-OCR{n:04d}", type=ElementType.TEXT,
            points=[(x + w / 2.0, y + h / 2.0)],
            text=word,
            bbox=(x, y, x + w, y + h),
            ocr_confidence=conf,
        ))
        n += 1
    return elements
