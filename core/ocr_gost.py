"""Dimension recognition: GOST/ESKD symbols, numbers, and linking to geometry.

Two entry points:

``recognize_dimensions(drawing)``
    Turns the TEXT elements already extracted by the parser (vector PDF text is
    exact — no OCR involved) into :class:`core.models.Dimension` objects and
    links each to the nearest drawing element.

``ocr_words(image)``
    Offline OCR fallback for raster scans. Uses RapidOCR (ONNX, fully local,
    bundled models) when available; falls back to a local Tesseract binary via
    pytesseract. Never used for vector PDFs. If neither engine is available it
    raises RuntimeError with a clear message — no network calls, no silent
    failure, no invented text. Known systematic: RapidOCR reads GOST Ø as
    "0" ("Ø40" → "040"); :func:`parse_dimension_text` maps zero-led integers to
    DIAMETER and flags them uncertain for human confirmation.

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

# chamfer: "2×45°", "2x45", "2*45 °", "C2", "С2" (GOST chamfer callout)
_CHAMFER_45 = re.compile(r"^(?P<c>\d{1,2}(?:[.,]\d{1,2})?)\s*[xхX×*]\s*45\s*°?$")
_CHAMFER_C = re.compile(r"^[CСcс](?P<c>\d{1,2}(?:[.,]\d{1,2})?)$")
# strict: "Ø50", "Ø 50.5", "⌀40", "R12", "M8x1.25", "120", "120,5"
_STRICT = re.compile(
    r"^(?P<prefix>Ø|⌀|∅|Φ|%%c|%%C|R|M)?\s*(?P<num>\d{1,4}(?:[.,]\d{1,4})?)(?:\s*[xхX×].*)?$"
)
# loose: same, but tolerate OCR confusions inside the numeric part (O/o→0, l→1, S→5)
_LOOSE_NUM = re.compile(r"^(?P<prefix>Ø|⌀|∅|Φ|%%c|%%C|R|M)?\s*(?P<num>[0-9OoIlSsB]{1,4}(?:[.,][0-9OoIlSsB]{1,4})?)(?:\s*[xхX×].*)?$")

_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
# zero-led integer, no decimal dot: "040" — RapidOCR lost the Ø glyph
_ZERO_LED_DIA = re.compile(r"^0(?P<num>\d{1,4}(?:[.,]\d{1,4})?)$")

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

    m = _CHAMFER_45.match(t)
    if m:
        value = _parse_number(m.group("c"))
        return (Symbol.CHAMFER, value, 0.9) if value else None
    m = _CHAMFER_C.match(t)
    if m:
        value = _parse_number(m.group("c"))
        return (Symbol.CHAMFER, value, 0.85) if value else None

    # RapidOCR systematically drops the Ø glyph in GOST diameter callouts
    # ("Ø40" → "040"). Linear dimensions never lead with 0, so this is a
    # diameter; confidence stays below the auto-accept threshold — the human
    # confirms the substitution.
    m = _ZERO_LED_DIA.match(t)
    if m:
        num = _parse_number(m.group("num"))
        return (Symbol.DIAMETER, num, 0.7) if num is not None else None

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


def _point_to_rect(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> float:
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def _segments_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        if abs(v) < 1e-12:
            return 0.0
        return 1.0 if v > 0 else -1.0

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4 and o1 != 0.0 and o2 != 0.0 and o3 != 0.0 and o4 != 0.0:
        return True
    # collinear/touching cases: treat endpoint-on-segment as intersection
    for p, q, s in ((c, d, (a, b)), (a, b, (c, d))):
        p1, q1 = s
        for p_ in (p, q):
            if abs((q1[0] - p1[0]) * (p_[1] - p1[1]) - (q1[1] - p1[1]) * (p_[0] - p1[0])) < 1e-9:
                if min(p1[0], q1[0]) - 1e-9 <= p_[0] <= max(p1[0], q1[0]) + 1e-9 and \
                   min(p1[1], q1[1]) - 1e-9 <= p_[1] <= max(p1[1], q1[1]) + 1e-9:
                    return True
    return False


def _bbox_edges(x0: float, y0: float, x1: float, y1: float):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


def _perpendicular_offset(anchor: tuple[float, float], e: VectorElement) -> float:
    """Perpendicular distance from the anchor to the candidate's line."""
    if len(e.points) != 2:
        return 0.0
    (ax, ay), (bx, by) = e.points
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0
    return abs((anchor[0] - ax) * dy - (anchor[1] - ay) * dx) / length


def _distance_bbox_to_element(bbox: tuple[float, float, float, float], e: VectorElement) -> float:
    """Distance from a text bounding box to an element (0 when touching)."""
    x0, y0, x1, y1 = bbox
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if len(e.points) == 2:
        a, b = e.points
        ax, ay = a
        bx, by = b
        # intersects the rect?
        if x0 - 1e-9 <= ax <= x1 + 1e-9 and y0 - 1e-9 <= ay <= y1 + 1e-9:
            return 0.0
        if x0 - 1e-9 <= bx <= x1 + 1e-9 and y0 - 1e-9 <= by <= y1 + 1e-9:
            return 0.0
        for e1, e2 in _bbox_edges(x0, y0, x1, y1):
            if _segments_intersect((ax, ay), (bx, by), e1, e2):
                return 0.0
        best = min(_distance_point_to_segment(px, py, ax, ay, bx, by) for px, py in corners)
        best = min(best, _point_to_rect(ax, ay, x0, y0, x1, y1),
                   _point_to_rect(bx, by, x0, y0, x1, y1))
        return best
    # fallback for degenerate elements: centre-to-element
    return _distance_point_to_element(((x0 + x1) / 2.0, (y0 + y1) / 2.0), e)


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


def _is_horizontal_dim_line(e: VectorElement) -> bool:
    if len(e.points) != 2:
        return False
    (ax, ay), (bx, by) = e.points
    dx, dy = abs(bx - ax), abs(by - ay)
    return dx > 1e-9 and dy <= 0.18 * dx


def _chain_links(elements, candidates):
    """Sequential linking for chain LINEAR dimensions (GOST цепочка размеров).

    Several LINEAR callouts on one baseline are linked in left→right order
    to sequential segments of their dimension line: the line is split at the
    midpoints between consecutive text centres and each text claims its own
    segment. The drawing carries no mid extension lines in this GOST style
    (chain ticks are arrow pairs on the line itself), so the texts are the
    segmentation evidence. Returns {text_id: (segment_element, distance)}.

    Called for scans; PDFs behave identically (their chain extension lines
    end at the line, so each line splits into the same sequential pieces).
    """
    texts = []
    for element in elements:
        if element.type is not ElementType.TEXT or not element.text:
            continue
        parsed = parse_dimension_text(element.text)
        if parsed and parsed[0] is Symbol.LINEAR:
            texts.append(element)
    groups: list[list[VectorElement]] = []
    for element in sorted(texts, key=lambda e: (e.points[0][1] if e.points else 0.0,
                                                e.points[0][0] if e.points else 0.0)):
        ay = element.points[0][1]
        placed = False
        for group in groups:
            gy = group[0].points[0][1]
            if abs(gy - ay) <= 1.2:
                group.append(element)
                placed = True
                break
        if not placed:
            groups.append([element])
    def _row_spans(hor):
        """Group horizontal candidates into rows; each row becomes one merged
        interval (row_min..row_max) — fragments of the same dimension line
        are all kept, gaps and all, since texts ride the row at any x."""
        rows: list[dict] = []
        for e in sorted(hor, key=lambda e: (e.points[0][1] + e.points[1][1]) / 2.0):
            y = (e.points[0][1] + e.points[1][1]) / 2.0
            (x0, y0), (x1, y1) = e.points
            xa, xb = sorted((x0, x1))
            for row in rows:
                if abs(row["y"] - y) <= 0.8:
                    row["members"].append(e)
                    row["y"] = (row["y"] * (len(row["members"]) - 1) + y) / len(row["members"])
                    row["x0"] = min(row["x0"], xa)
                    row["x1"] = max(row["x1"], xb)
                    row["stroke_width"] = max(row["stroke_width"], e.stroke_width)
                    row["arrow_end"] = row["arrow_end"] or e.arrow_end
                    break
            else:
                rows.append({"y": y, "x0": xa, "x1": xb, "members": [e],
                             "id": e.id, "stroke_width": e.stroke_width,
                             "arrow_end": e.arrow_end})
        return rows

    out: dict[str, tuple[VectorElement, float]] = {}
    rows = _row_spans([c for c in candidates if _is_horizontal_dim_line(c)])
    for group in groups:
        if len(group) < 2:
            continue
        members = sorted(group, key=lambda e: e.points[0][0])
        baseline_y = sum(e.points[0][1] for e in members) / len(members)
        hor = [r for r in rows if abs(r["y"] - baseline_y) <= 6.0]
        if not hor:
            continue
        # pick the row with the largest ink overlap with the texts' x-span
        tx0 = min(e.bbox[0] for e in members if e.bbox)
        tx1 = max(e.bbox[2] for e in members if e.bbox)

        def _overlap(r):
            return max(0.0, min(r["x1"], tx1) - max(r["x0"], tx0))

        line = max(hor, key=_overlap)
        ax0, ax1, ay = line["x0"], line["x1"], line["y"]
        line_id, line_sw, line_arrow = line["id"], line["stroke_width"], line["arrow_end"]
        centres = [e.points[0][0] for e in members]
        cuts = [ax0] + [(a + b) / 2.0 for a, b in zip(centres, centres[1:])] + [ax1]
        if any(cuts[i] >= cuts[i + 1] for i in range(len(cuts) - 1)):
            continue  # non-monotone split — leave the group to plain linking
        for k, element in enumerate(members):
            seg = VectorElement(
                id=f"{line_id}#seg{k}", type=ElementType.DIMENSION_LINE,
                points=[(cuts[k], ay), (cuts[k + 1], ay)],
                stroke_width=line_sw, dash=None,
                bbox=(cuts[k], ay, cuts[k + 1], ay),
                arrow_end=line_arrow,
            )
            d = (_distance_bbox_to_element(element.bbox, seg) if element.bbox
                 else _distance_point_to_element(element.points[0], seg))
            out[element.id] = (seg, d)
    return out


def recognize_dimensions(drawing: Drawing) -> list[Dimension]:
    """Recognize dimension texts in a parsed drawing and link them to geometry."""
    dimensions: list[Dimension] = []
    # Symbol carriers are DIMENSION_LINE elements only: contours and the revolution
    # AXIS are never dimension callouts, so they cannot "link" a text.
    candidates = [e for e in drawing.elements
                  if e.type is ElementType.DIMENSION_LINE]
    chain_map = _chain_links(drawing.elements, candidates)

    def _axis_aligned(e) -> bool:
        if len(e.points) != 2:
            return False
        (ax, ay), (bx, by) = e.points
        dx, dy = abs(bx - ax), abs(by - ay)
        if max(dx, dy) < 1e-9:
            return False
        return dy <= 0.18 * dx or dx <= 0.18 * dy

    def _candidates_for(symbol: Symbol):
        if symbol is Symbol.LINEAR:
            # linear dimensions ride straight (horizontal/vertical) dimension
            # lines or extension lines — diagonal leader strokes are for R/Ø/chamfers
            return [e for e in candidates if _axis_aligned(e)]
        return candidates

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
        text_bbox = element.bbox
        if text_bbox:
            anchor = ((text_bbox[0] + text_bbox[2]) / 2.0,
                      (text_bbox[1] + text_bbox[3]) / 2.0)
        else:
            anchor = element.points[0] if element.points else (0.0, 0.0)

        nearest_id, nearest_score = None, math.inf
        nearest_d = math.inf
        nearest_perp = math.inf
        nearest_arrow = False
        # a text on a multi-dimension chain links deterministically to its
        # sequential segment; the plain candidates act as fallback only
        chain = chain_map.get(element.id) if symbol is Symbol.LINEAR else None
        if chain is not None and chain[1] <= _LINK_RADIUS_MM:
            seg, d = chain
            nearest_id, nearest_score, nearest_d = seg.id, d, d
            nearest_arrow = seg.arrow_end
            pool = []
        else:
            pool = list(_candidates_for(symbol))
        for cand in pool:
            d = (_distance_bbox_to_element(text_bbox, cand) if text_bbox
                 else _distance_point_to_element(anchor, cand))
            perp = _perpendicular_offset(anchor, cand)
            # LINEAR dims ride straight dimension lines: rank by plain distance
            # (perpendicular offset is meaningless for lines of the other orientation).
            # Ø/R/chamfer callouts rank axis-aligned carriers Square-on-centre and
            # diagonal leaders by distance. A filled arrowhead at a stroke end is
            # mild evidence the stroke is a dimension carrier (tie-breaker).
            if symbol is Symbol.LINEAR:
                score = d - (0.4 if cand.arrow_end else 0.0)
            else:
                score = perp if _axis_aligned(cand) else d
            if score < nearest_score - 1e-6 or (
                abs(score - nearest_score) <= 1e-6 and d < nearest_d
            ):
                nearest_score, nearest_id, nearest_d, nearest_perp = score, cand.id, d, perp
                nearest_arrow = cand.arrow_end

        linked = nearest_id is not None and nearest_score <= _LINK_RADIUS_MM and nearest_d <= _LINK_RADIUS_MM
        if not linked:
            confidence = min(confidence, 0.6)
        elif nearest_d > _FAR_LINK_MM:
            # 5–9 mm: plausible but far — keep it below auto-accept unless
            # there is independent evidence (filled arrowhead at the stroke end)
            confidence = min(confidence, 0.95 if nearest_arrow else 0.9)
        # RapidOCR systematically drops the Ø glyph ("Ø40" → "040"). When such
        # a text is near a leader/axis it is almost certainly that leader's
        # diameter; far from any geometry it is no annotation at all.
        if symbol is Symbol.DIAMETER and _ZERO_LED_DIA.match(element.text.strip()):
            confidence = 0.8 if linked else min(confidence, 0.5)

        dimensions.append(Dimension(
            id=f"DIM-{idx:04d}", symbol=symbol, value=value,
            raw_text=element.text, confidence=round(confidence, 3),
            linked_element_id=nearest_id if linked else None,
            is_uncertain=confidence < CONFIDENCE_THRESHOLD,
            anchor=anchor,
        ))
        idx += 1
    # Zero-led Ø reads whose value matches the measured geometry are proposed
    # as "Ø<value>" (confidence 0.85, still uncertain — never auto-applied).
    from core.diameter_recovery import propose_geometry_bound_diameters
    dimensions = propose_geometry_bound_diameters(dimensions, drawing)
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
    """Raster-OCR fallback for scanned drawings (offline, local).

    Tries RapidOCR (ONNX runtime, models bundled in the wheel — fully
    offline) and falls back to Tesseract via pytesseract. Returns TEXT
    elements (same shape as the vector parser produces). Raises RuntimeError
    if no engine is available — callers must surface that to the user
    instead of continuing blindly.
    """
    words = _rapid_ocr_words(image)
    if words is not None:
        return words
    return _tesseract_words(image)


def _rapid_ocr_words(image):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    try:
        result, _ = RapidOCR()(image)
    except Exception:
        return None

    elements: list[VectorElement] = []
    for n, (box, text, conf) in enumerate(result or []):
        text = str(text).strip()
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        elements.append(VectorElement(
            id=f"T-OCR{n:04d}", type=ElementType.TEXT,
            points=[((x0 + x1) / 2.0, (y0 + y1) / 2.0)],
            text=text,
            bbox=(x0, y0, x1, y1),
            ocr_confidence=float(conf) * 100.0,
        ))
    return elements


def _tesseract_words(image):
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - depends on system
        raise RuntimeError(
            "No local OCR engine is available. Install 'rapidocr-onnxruntime' "
            "(preferred, bundles offline ONNX models) or the system "
            "'tesseract-ocr' package with 'pip install pytesseract'. "
            "Vector PDFs do not need OCR."
        ) from exc

    config = "--psm 6 -c tessedit_char_whitelist=0123456789Ø⌀RMrm.,x×°*CcСс "
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
