"""Text-parsing rules for GOST/ESKD dimension strings."""

from __future__ import annotations

from core.models import Symbol
from core.ocr_gost import parse_dimension_text


def test_diameter_variants():
    for text in ("Ø50", "Ø 50", "⌀40", "∅40", "Φ42", "%%c50"):
        parsed = parse_dimension_text(text)
        assert parsed is not None, text
        assert parsed[0] is Symbol.DIAMETER


def test_radius_and_thread():
    assert parse_dimension_text("R12")[0] is Symbol.RADIUS
    assert parse_dimension_text("M8")[0] is Symbol.THREAD


def test_linear_comma_decimal():
    symbol, value, conf = parse_dimension_text("120,5")
    assert symbol is Symbol.LINEAR
    assert value == 120.5
    assert conf >= 0.9


def test_ocr_confusable_gets_low_confidence():
    parsed = parse_dimension_text("Ø5O")
    assert parsed is not None
    symbol, value, conf = parsed
    assert symbol is Symbol.DIAMETER
    assert value == 50.0
    assert conf < 0.85  # must be flagged uncertain downstream


def test_plain_annotation_is_ignored():
    assert parse_dimension_text("Масштаб") is None
    assert parse_dimension_text("ВАЛ") is None
    assert parse_dimension_text("") is None
