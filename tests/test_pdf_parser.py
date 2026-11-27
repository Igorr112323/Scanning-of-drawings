"""PDF parsing tests against the synthetic A3 example (scale 1:1, mm)."""

from __future__ import annotations

import math

import pytest

from core.models import ElementType, Symbol
from core.ocr_gost import recognize_dimensions
from core.pdf_parser import parse_pdf
from data.examples.generate_example import generate


@pytest.fixture(scope="module")
def example_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("examples") / "flange_shaft_demo.pdf"
    generate(path)
    return path


def test_parse_extracts_all_stroke_text_elements(example_pdf):
    drawing = parse_pdf(example_pdf)
    counts = {}
    for element in drawing.elements:
        counts[element.type] = counts.get(element.type, 0) + 1
    assert counts[ElementType.CONTOUR] > 0
    assert counts[ElementType.AXIS] >= 1
    assert counts[ElementType.DIMENSION_LINE] > 0
    assert counts[ElementType.TEXT] > 0
    # The sheet is A3 landscape: 420 x 297 mm
    assert math.isclose(drawing.page_width, 420.0, abs_tol=0.5)
    assert math.isclose(drawing.page_height, 297.0, abs_tol=0.5)


def test_axis_detected(example_pdf):
    drawing = parse_pdf(example_pdf)
    axis_y = drawing.views[0].axis_y
    assert axis_y == pytest.approx(148.5, abs=0.5)


def test_profile_reconstructed(example_pdf):
    drawing = parse_pdf(example_pdf)
    pts = [(round(p.x, 2), round(p.r, 2)) for p in drawing.profile]
    # half-profile, closed on the axis, three cylinder surfaces
    assert pts[0] == (30.0, 0.0)
    assert pts[-1] == (330.0, 0.0)
    radii = {r for _, r in pts if r > 0}
    assert radii == {25.0, 45.0, 20.0}


def test_dimensions_recognized(example_pdf):
    drawing = parse_pdf(example_pdf)
    dims = recognize_dimensions(drawing)
    diameters = {d.value for d in dims if d.symbol is Symbol.DIAMETER}
    linears = sorted(d.value for d in dims if d.symbol is Symbol.LINEAR)
    assert diameters == {50.0, 90.0, 40.0}
    assert linears == [80.0, 100.0, 120.0, 300.0]
    # the synthetic drawing is clean — no dimension may be flagged uncertain
    assert all(not d.is_uncertain for d in dims)
    assert all(d.linked_element_id is not None for d in dims)


def test_parse_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_pdf("does/not/exist.pdf")


def test_parse_rejects_non_pdf(tmp_path):
    path = tmp_path / "drawing.txt"
    path.write_text("not a pdf")
    with pytest.raises(ValueError):
        parse_pdf(path)


def test_fillet_arc_outline_reconstructs_profile(tmp_path):
    """Regression for the zenodo page_001 failure (run 2026-11-27): GOST
    fillets arrive as cubic Bezier curves; v1 ignored curves, leaving
    coverage gaps in the half-profile -> 'no revolution profile
    reconstructed' -> pipeline NO_DIMS with 47 dims parsed. The curves must
    be flattened to chords and the profile rebuilt."""
    import fitz

    pdf = tmp_path / "fillet_shaft.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    W = 1.4
    page.draw_line(fitz.Point(80, 240), fitz.Point(380, 240), color=(0, 0, 0), width=W)
    page.draw_bezier(fitz.Point(380, 240), fitz.Point(405, 240),
                     fitz.Point(415, 270), fitz.Point(440, 270), color=(0, 0, 0), width=W)
    page.draw_line(fitz.Point(440, 270), fitz.Point(720, 270), color=(0, 0, 0), width=W)
    page.draw_line(fitz.Point(80, 360), fitz.Point(380, 360), color=(0, 0, 0), width=W)
    page.draw_bezier(fitz.Point(380, 360), fitz.Point(405, 360),
                     fitz.Point(415, 330), fitz.Point(440, 330), color=(0, 0, 0), width=W)
    page.draw_line(fitz.Point(440, 330), fitz.Point(720, 330), color=(0, 0, 0), width=W)
    page.draw_line(fitz.Point(80, 240), fitz.Point(80, 360), color=(0, 0, 0), width=W)
    page.draw_line(fitz.Point(720, 270), fitz.Point(720, 330), color=(0, 0, 0), width=W)
    x, i = 40.0, 0  # traced dash-dot: separate thin segments, no dash attribute
    while x < 780.0:
        length = (60.0, 5.0)[i % 2]
        page.draw_line(fitz.Point(x, 300), fitz.Point(min(x + length, 780.0), 300),
                       color=(0, 0, 0), width=0.4)
        x += length + 8.0
        i += 1
    page.insert_text(fitz.Point(620, 120), "Ø120", fontsize=10)
    doc.save(pdf)
    doc.close()

    drawing = parse_pdf(pdf)
    assert drawing.profile, "fillet arc must not void the half-profile"
    radii = sorted({round(p.r, 1) for p in drawing.profile})
    assert max(radii) == pytest.approx(21.2, abs=0.2)
    assert min(r for r in radii if r > 0) == pytest.approx(10.6, abs=0.2)


def test_quad_item_parsed_as_closed_shape(tmp_path):
    """Regression for the cabaffc CRASH 'IndexError: tuple index out of range'
    on the zenodo corpus (all 4 candidates): fitz 'qu' items are Quads, not
    quadratic Beziers; item[2]/item[3] do not exist."""
    import fitz

    pdf = tmp_path / "quad_shaft.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    # small registration mark drawn as a quad (outside the outline)
    quad = fitz.Quad(fitz.Point(600, 80), fitz.Point(640, 80),
                     fitz.Point(640, 110), fitz.Point(600, 110))
    page.draw_quad(quad, color=(0, 0, 0), width=1.0)
    page.draw_rect(fitz.Rect(80, 262, 720, 338), color=(0, 0, 0), width=1.4)
    x, i = 40.0, 0
    while x < 760.0:
        length = (60.0, 5.0)[i % 2]
        page.draw_line(fitz.Point(x, 300), fitz.Point(min(x + length, 760.0), 300),
                       color=(0, 0, 0), width=0.4)
        x += length + 8.0
        i += 1
    page.insert_text(fitz.Point(600, 150), "Ø120", fontsize=10)
    doc.save(pdf)
    doc.close()

    drawing = parse_pdf(pdf)
    assert drawing.profile, "profile must survive quad items"
