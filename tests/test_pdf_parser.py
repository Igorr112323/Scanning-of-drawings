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
