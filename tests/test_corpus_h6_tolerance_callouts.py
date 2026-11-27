"""Regression tests for hypothesis H6: tolerance callouts without an Ø/R/M
prefix were silently dropped from the dimension list (they parsed to None).

Fix (core/ocr_gost.parse_dimension_text): strip trailing tolerance suffixes
(±…/+…/−…/-… groups and GOST/ISO tolerance classes like h6/H7/js6) from the
stem before matching; the stripped stem is parsed normally with confidence
capped at 0.7, so the dimension is kept, never auto-applied, and always
needs human confirmation.

General fix — no file ids, no literal dimension special-casing.
"""

from __future__ import annotations

import pytest

from core.models import Symbol
from core.ocr_gost import parse_dimension_text


@pytest.mark.parametrize("text,symbol,value", [
    ("40±0.05", Symbol.LINEAR, 40.0),
    ("Ø40±0.1", Symbol.DIAMETER, 40.0),
    ("40±0,1", Symbol.LINEAR, 40.0),
    ("120±0,2", Symbol.LINEAR, 120.0),
    ("Ø40h6", Symbol.DIAMETER, 40.0),
    ("Ø40H7", Symbol.DIAMETER, 40.0),
    ("50h6", Symbol.LINEAR, 50.0),
    ("Ø40js6", Symbol.DIAMETER, 40.0),
    ("32k6", Symbol.LINEAR, 32.0),
    ("40 +0.05", Symbol.LINEAR, 40.0),
    ("40-0.05", Symbol.LINEAR, 40.0),
])
def test_corpus_h6_tolerance_suffix_stripped(text, symbol, value):
    parsed = parse_dimension_text(text)
    assert parsed is not None, text
    sym, val, conf = parsed
    assert sym is symbol
    assert val == pytest.approx(value)
    assert conf <= 0.7, "tolerance-stripped dims must never auto-accept"


@pytest.mark.parametrize("text,symbol", [
    ("M20x1.5", Symbol.THREAD),
    ("M12", Symbol.THREAD),
    ("Ø40", Symbol.DIAMETER),
    ("R12,5", Symbol.RADIUS),
    ("2×45°", Symbol.CHAMFER),
    ("C2", Symbol.CHAMFER),
])
def test_corpus_h6_plain_callouts_unaffected(text, symbol):
    # plain callouts must keep their 0.9+ confidence (no tolerance to strip)
    parsed = parse_dimension_text(text)
    assert parsed is not None
    sym, _val, conf = parsed
    assert sym is symbol
    assert conf >= 0.85


def test_corpus_h6_thread_m_prefix_survives():
    # regression guard: the tolerance-class strip must not eat "M20" -> ""
    parsed = parse_dimension_text("M20")
    assert parsed == (Symbol.THREAD, 20.0, 0.95)
