"""Scan pipeline (v1.1): raster image → cleaned Drawing → dimensions.

Used for scanned ESKD sheets (clean scans only — no photos of paper). Steps:

    cv2.imread → preprocess_scan (deskew/denoise/binarize)
              → vectorize (CONTOUR / DIMENSION_LINE / AXIS / HATCH by stroke width & pattern)
              → ocr_words (local Tesseract, GOST whitelist)
              → mm normalization (DPI from file metadata, default 200 DPI)
              → extract_revolution → Drawing

Honesty rules (identical to the vector path):
- OCR words that cannot be parsed or linked to a line stay ``is_uncertain`` —
  the verification screen flags them; the app never invents a dimension.
- A scan below usable quality produces FEWER dimensions, not made-up ones;
  callers must surface that to the user (see app/ui/main_window.py).
- OCR linking is distance-based; arrow-direction disambiguation is not
  attempted — anything ambiguous is flagged for the human, never guessed.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from core.geometry import extract_revolution
from core.models import Drawing, ElementType, VectorElement
from core.ocr_gost import ocr_words
from core.scan_preprocess import preprocess_scan
from core.vectorize import vectorize

_MM_PER_INCH = 25.4
_DEFAULT_DPI = 200.0


def read_dpi(path: str | Path) -> float | None:
    """Best-effort DPI from file metadata (PNG pHYs / TIFF / JPEG EXIF dpi)."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            dpi = img.info.get("dpi") or img.info.get("jfif_density")
            if dpi:
                value = float(dpi[0] if isinstance(dpi, tuple) else dpi)
                if 50.0 <= value <= 1200.0:
                    return value
    except Exception:
        return None
    return None


def _scale_elements(elements: list[VectorElement], factor: float) -> list[VectorElement]:
    out: list[VectorElement] = []
    for e in elements:
        pts = [(x * factor, y * factor) for (x, y) in e.points]
        bbox = tuple(v * factor for v in e.bbox) if e.bbox else None
        out.append(VectorElement(
            id=e.id, type=e.type, points=pts,
            stroke_width=e.stroke_width * factor, dash=e.dash,
            text=e.text, bbox=bbox, ocr_confidence=e.ocr_confidence,
        ))
    return out


def build_drawing_from_arrays(
    cleaned: np.ndarray,
    width_px: int,
    height_px: int,
    dpi: float,
    source_path: str,
    ocr: bool = True,
) -> Drawing:
    """Shared core of the scan path, kept separate for tests (synthetic scans)."""
    mm_per_px = _MM_PER_INCH / dpi
    elements = _scale_elements(vectorize(cleaned), mm_per_px)
    if ocr:
        words = _scale_elements(ocr_words(cleaned), mm_per_px)
        boxes = [w.bbox for w in words if w.bbox]
        if boxes:
            pad = 1.0  # mm — text ink extends past OCRed word boxes

            def _rect_distance(x: float, y: float, box) -> float:
                x0, y0, x1, y1 = box
                dx = max(x0 - x, 0.0, x - x1)
                dy = max(y0 - y, 0.0, y - y1)
                return max(dx, dy)

            def _is_diagonal(e) -> bool:
                (x0, y0), (x1, y1) = e.points
                sx, sy = abs(x1 - x0), abs(y1 - y0)
                span = max(sx, sy)
                if span <= 0.0:
                    return False
                # axis-parallel outline strokes are safe; only diagonals
                # (10°..80°) can be leaders
                return min(sx, sy) / span > 0.18

            def _leader_stroke(e) -> bool:
                """A diagonal stroke attached to a word box is its callout
                leader — glyphs sit inside the box, the leader touches it;
                the part outline never terminates on a text box."""
                if e.type is ElementType.AXIS or len(e.points) != 2:
                    return False
                if not _is_diagonal(e):
                    return False
                return any(
                    _rect_distance(p[0], p[1], b) <= pad
                    for p in e.points
                    for b in boxes
                )

            def _glyph_stroke(e) -> bool:
                """A stroke that is mostly INSIDE a word's box is glyph mass.

                Long engineering strokes may clip a word box (a diameter line
                grazes its own Ø text) — those are kept.
                """
                if e.type is ElementType.AXIS or len(e.points) != 2:
                    return False
                p0, p1 = e.points
                sx0, sx1 = sorted((p0[0], p1[0]))
                sy0, sy1 = sorted((p0[1], p1[1]))
                span_x, span_y = sx1 - sx0, sy1 - sy0
                span = max(span_x, span_y)
                if span <= 0.0:
                    return False
                horizontal = span_x >= span_y
                for x0, y0, x1, y1 in boxes:
                    if sx1 < x0 - pad or sx0 > x1 + pad:
                        continue
                    if sy1 < y0 - pad or sy0 > y1 + pad:
                        continue
                    if horizontal:
                        contained = min(sx1, x1 + pad) - max(sx0, x0 - pad)
                    else:
                        contained = min(sy1, y1 + pad) - max(sy0, y0 - pad)
                    if contained / span >= 0.5:
                        return True
                return False

            # glyph pixels for OCR'd words are text, not geometry; callout
            # leaders are text attachments, not part outline either
            elements = [e for e in elements if not _glyph_stroke(e) and not _leader_stroke(e)]
        elements.extend(words)

    page_w, page_h = width_px * mm_per_px, height_px * mm_per_px
    profile, bore, orientation, _axis = extract_revolution(elements)
    drawing = Drawing(
        source_path=source_path,
        page_width=page_w,
        page_height=page_h,
        elements=elements,
        profile=profile,
        bore_diameter=bore,
    )
    from core.models import View
    drawing.views = [View(
        name="main",
        bbox=(0.0, 0.0, page_w, page_h),
        elements=elements,
        axis_y=None,  # axis position lives in transposed coordinates; profile is what matters
    )]
    return drawing


def parse_scan(path: str | Path, dpi: float | None = None, ocr: bool = True) -> Drawing:
    """Full scan path: image file → cleaned binarized Drawing.

    Raises ValueError for unreadable/empty images. OCR failures propagate as
    RuntimeError with an actionable message (Tesseract missing) — callers must
    show it instead of continuing with empty text silently.
    """
    path = Path(path)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Не удалось прочитать изображение: {path.name}")
    cleaned = preprocess_scan(image)
    actual_dpi = dpi if dpi is not None else (read_dpi(path) or _DEFAULT_DPI)
    h, w = cleaned.shape[:2]
    drawing = build_drawing_from_arrays(cleaned, w, h, actual_dpi, str(path), ocr=ocr)
    return drawing
