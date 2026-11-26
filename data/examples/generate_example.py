"""Generate the synthetic demo drawing: a stepped shaft (вал ступенчатый).

Generated with code on purpose — committed example PDFs must be reproducible.
Sheet A3 landscape, scale 1:1, millimetres. Layout:

    Ø50 journal  x  30–150   (120 mm)
    Ø90 flange   x 150–230   (80 mm)
    Ø40 journal  x 230–330   (100 mm)
    overall length            300 mm

Half-section style: full symmetric outline + dash-dot centre axis, diameter
dimensions with extension/section-style placement GOST Условные обозначения,
chain length dimensions below the view.

Usage:  python -m data.examples.generate_example [output.pdf]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import fitz  # PyMuPDF

PT_PER_MM = 72.0 / 25.4

PAGE_W_MM, PAGE_H_MM = 420.0, 297.0
AXIS_Y_MM = 148.5

CONTOUR_W = 0.7 * PT_PER_MM      # GOST main line
THIN_W = 0.35 * PT_PER_MM        # GOST thin line (dimensions/extensions)
AXIS_DASH = "[11.34 4.25 2.83 4.25] 0"  # dash-dot in points (4 mm / 1.5 / 1 / 1.5)
FONT = "helv"
FONT_SIZE = 13.0


def _mm(v: float) -> float:
    return v * PT_PER_MM


def _pt(x_mm: float, y_mm: float) -> fitz.Point:
    return fitz.Point(_mm(x_mm), _mm(y_mm))


def _text(page: fitz.Page, x_mm: float, baseline_y_mm: float, text: str, size: float = FONT_SIZE) -> None:
    length = fitz.get_text_length(text, fontname=FONT, fontsize=size)
    page.insert_text(
        fitz.Point(_mm(x_mm) - length / 2.0, _mm(baseline_y_mm)),
        text, fontname=FONT, fontsize=size, color=(0, 0, 0),
    )


def _arrowhead(page: fitz.Page, tip_x_mm: float, tip_y_mm: float, angle_rad: float, size_mm: float = 3.2) -> None:
    """Small filled triangle; parser ignores fill-only paths."""
    tip = fitz.Point(_mm(tip_x_mm), _mm(tip_y_mm))
    back1 = fitz.Point(_mm(tip_x_mm - size_mm * math.cos(angle_rad - 0.42)),
                       _mm(tip_y_mm - size_mm * math.sin(angle_rad - 0.42)))
    back2 = fitz.Point(_mm(tip_x_mm - size_mm * math.cos(angle_rad + 0.42)),
                       _mm(tip_y_mm - size_mm * math.sin(angle_rad + 0.42)))
    shape = page.new_shape()
    shape.draw_polyline([tip, back1, back2])
    shape.finish(fill=(0, 0, 0), color=None, even_odd=False)
    shape.commit()


def generate(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()
    page = doc.new_page(width=_mm(PAGE_W_MM), height=_mm(PAGE_H_MM))

    # ------------------------------------------------------------------ outline
    outline = [
        (30, 123.5), (150, 123.5), (150, 103.5), (230, 103.5), (230, 128.5),
        (330, 128.5), (330, 168.5), (230, 168.5), (230, 193.5), (150, 193.5),
        (150, 173.5), (30, 173.5), (30, 123.5),
    ]
    shape = page.new_shape()
    shape.draw_polyline([_pt(x, y) for x, y in outline])
    shape.finish(color=(0, 0, 0), width=CONTOUR_W, dashes=None, closePath=True)
    shape.commit()

    # ------------------------------------------------------------ centre axis
    shape = page.new_shape()
    shape.draw_line(_pt(15, AXIS_Y_MM), _pt(345, AXIS_Y_MM))
    shape.finish(color=(0, 0, 0), width=THIN_W, dashes=AXIS_DASH)
    shape.commit()

    # ------------------------------------------------- diameter dimension lines
    # GOST: dimension line across the feature with arrowheads at both ends
    for x_mm, y_top, y_bot in ((90, 123.5, 173.5), (190, 103.5, 193.5), (280, 128.5, 168.5)):
        shape = page.new_shape()
        shape.draw_line(_pt(x_mm, y_top), _pt(x_mm, y_bot))
        shape.finish(color=(0, 0, 0), width=THIN_W, dashes=None)
        shape.commit()
        _arrowhead(page, x_mm, y_top, math.pi / 2)     # pointing up
        _arrowhead(page, x_mm, y_bot, -math.pi / 2)    # pointing down

    _text(page, 90, 120.5, "Ø50")   # bbox center ≈ 115.5 — ~8 mm above the line top (inside link radius)
    _text(page, 190, 99.5, "Ø90")
    _text(page, 280, 125.5, "Ø40")

    # --------------------------------------------------------- extension lines
    for x_mm, y_from in ((30, 173.5), (150, 193.5), (230, 193.5), (330, 168.5)):
        shape = page.new_shape()
        shape.draw_line(_pt(x_mm, y_from + 2), _pt(x_mm, 254))
        shape.finish(color=(0, 0, 0), width=THIN_W, dashes=None)
        shape.commit()

    # -------------------------------------------------- overall length dimension
    shape = page.new_shape()
    shape.draw_line(_pt(30, 224), _pt(330, 224))
    shape.finish(color=(0, 0, 0), width=THIN_W, dashes=None)
    shape.commit()
    _arrowhead(page, 30, 224, 0.0)
    _arrowhead(page, 330, 224, math.pi)
    _text(page, 180, 220.5, "300")

    # --------------------------------------------------------- chain dimensions
    shape = page.new_shape()
    shape.draw_line(_pt(30, 250), _pt(330, 250))
    shape.finish(color=(0, 0, 0), width=THIN_W, dashes=None)
    shape.commit()
    for x_mm, angle in ((30, 0.0), (150, math.pi), (230, 0.0), (330, math.pi)):
        _arrowhead(page, x_mm, 250, angle)
    _text(page, 90, 246.5, "120")
    _text(page, 190, 246.5, "80")
    _text(page, 280, 246.5, "100")

    # ------------------------------------------------------------ caption texts
    _text(page, 90, 280, "ДЕМО: ВАЛ СТУПЕНЧАТЫЙ", size=10.0)
    _text(page, 90, 290, "Масштаб 1:1", size=8.0)

    doc.save(path, deflate=True)
    doc.close()
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("flange_shaft_demo.pdf")
    generate(out)
    print(f"Example drawing written to {out}")
