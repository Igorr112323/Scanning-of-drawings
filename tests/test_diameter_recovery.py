"""Ø recovery via geometry: proposals, never auto-application.

RapidOCR drops the Ø glyph ("Ø60" → "060"). The recovery cross-checks the
printed number against diameters measured from the drawn strokes (±r about
the revolution axis) and the extracted profile. A proposal requires:

    zero-led DIAMETER text  AND  linked to a leader  AND  a measured diameter
    within scan tolerance.

Anything else stays uncertain — nothing is invented.
"""

from __future__ import annotations

from core.diameter_recovery import measured_diameters, propose_geometry_bound_diameters
from core.models import Dimension, Drawing, ElementType, Symbol, VectorElement


def _line(id: str, x0: float, y0: float, x1: float, y1: float,
          type: ElementType) -> VectorElement:
    return VectorElement(id=id, type=type, points=[(x0, y0), (x1, y1)],
                         bbox=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
                         stroke_width=1.6 if type is ElementType.CONTOUR else 0.6)


def _drawing(elements, bore: float | None = None) -> Drawing:
    return Drawing(source_path="test.png", page_width=300.0, page_height=200.0,
                   elements=elements, profile=[], bore_diameter=bore)


def _zero_led(raw: str, value: float, linked: str | None = "L-1",
              anchor: tuple[float, float] = (60.0, 30.0)) -> Dimension:
    return Dimension(id="DIM-1", symbol=Symbol.DIAMETER, value=value, raw_text=raw,
                     confidence=0.8, linked_element_id=linked, is_uncertain=True,
                     anchor=anchor)


def _shaft_with(y_top: float, y_bot: float, axis_y: float = 100.0) -> Drawing:
    elements = [
        _line("A-0", 0.0, axis_y, 300.0, axis_y, ElementType.AXIS),
        _line("S-top", 0.0, y_top, 300.0, y_top, ElementType.CONTOUR),
        _line("S-bot", 0.0, y_bot, 300.0, y_bot, ElementType.CONTOUR),
        _line("L-1", 60.0, y_top, 60.0, y_top - 25.0, ElementType.DIMENSION_LINE),
    ]
    return _drawing(elements)


def test_matching_geometry_proposes_diameter():
    # strokes at ±30 mm about the axis → measured Ø60
    drawing = _shaft_with(70.0, 130.0)
    (dim,) = propose_geometry_bound_diameters([_zero_led("060", 60.0)], drawing)
    assert dim.raw_text == "Ø60"
    assert dim.value == 60.0
    assert dim.proposed_by_geometry is True
    assert dim.confidence == 0.85
    assert dim.is_uncertain is True          # one click to confirm — never auto-applied
    assert dim.linked_element_id == "L-1"    # link preserved


def test_mismatching_geometry_not_proposed():
    # geometry says Ø55; OCR read "060" — no proposal, stays for the user
    drawing = _shaft_with(72.5, 127.5)
    (dim,) = propose_geometry_bound_diameters([_zero_led("060", 60.0)], drawing)
    assert dim.raw_text == "060"
    assert dim.proposed_by_geometry is False
    assert dim.is_uncertain is True


def test_bore_wall_match_proposed():
    # inner bore walls at ±6.1 mm (Ø12.2), outer Ø40 — OCR read "012"
    elements = [
        _line("A-0", 0.0, 100.0, 300.0, 100.0, ElementType.AXIS),
        _line("S-top", 0.0, 80.0, 300.0, 80.0, ElementType.CONTOUR),
        _line("S-bot", 0.0, 120.0, 300.0, 120.0, ElementType.CONTOUR),
        _line("B-top", 0.0, 93.9, 300.0, 93.9, ElementType.CONTOUR),
        _line("B-bot", 0.0, 106.1, 300.0, 106.1, ElementType.CONTOUR),
        _line("L-1", 240.0, 80.0, 240.0, 55.0, ElementType.DIMENSION_LINE),
    ]
    drawing = _drawing(elements, bore=12.2)
    (dim,) = propose_geometry_bound_diameters(
        [_zero_led("012", 12.0, anchor=(240.0, 55.0))], drawing)
    assert dim.raw_text == "Ø12"
    assert dim.proposed_by_geometry is True


def test_measured_diameters_collects_both_families():
    elements = [
        _line("A-0", 0.0, 100.0, 300.0, 100.0, ElementType.AXIS),
        _line("S-top", 0.0, 80.0, 300.0, 80.0, ElementType.CONTOUR),
        _line("S-bot", 0.0, 120.0, 300.0, 120.0, ElementType.CONTOUR),
        _line("B-top", 0.0, 93.9, 300.0, 93.9, ElementType.CONTOUR),
        _line("B-bot", 0.0, 106.1, 300.0, 106.1, ElementType.CONTOUR),
    ]
    drawing = _drawing(elements, bore=12.2)
    measured = measured_diameters(drawing, 150.0)
    assert any(abs(m - 40.0) < 0.1 for m in measured)
    assert any(abs(m - 12.2) < 0.1 for m in measured)


def test_no_axis_no_proposal():
    elements = [
        _line("S-top", 0.0, 70.0, 300.0, 70.0, ElementType.CONTOUR),
        _line("S-bot", 0.0, 130.0, 300.0, 130.0, ElementType.CONTOUR),
        _line("L-1", 60.0, 70.0, 60.0, 45.0, ElementType.DIMENSION_LINE),
    ]
    drawing = _drawing(elements)
    (dim,) = propose_geometry_bound_diameters([_zero_led("060", 60.0)], drawing)
    assert dim.raw_text == "060"
    assert dim.proposed_by_geometry is False


def test_unlinked_dimension_not_proposed():
    drawing = _shaft_with(70.0, 130.0)
    (dim,) = propose_geometry_bound_diameters([_zero_led("060", 60.0, linked=None)], drawing)
    assert dim.raw_text == "060"
    assert dim.proposed_by_geometry is False


def test_recovery_is_idempotent():
    drawing = _shaft_with(70.0, 130.0)
    once = propose_geometry_bound_diameters([_zero_led("060", 60.0)], drawing)
    twice = propose_geometry_bound_diameters(once, drawing)
    assert once[0].raw_text == twice[0].raw_text == "Ø60"
    assert twice[0].proposed_by_geometry is True


def test_confidence_boundary_stays_uncertain():
    drawing = _shaft_with(70.0, 130.0)
    (dim,) = propose_geometry_bound_diameters([_zero_led("060", 60.0)], drawing)
    assert dim.confidence == 0.85  # exactly at threshold — uncertain, never auto-applied
    assert dim.is_uncertain is True
