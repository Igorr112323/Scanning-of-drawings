"""Constraint solver tests: scale inference, contradictions, no hallucinations."""

from __future__ import annotations

from core.constraint_solver import solve_constraints
from core.models import Dimension, ProfilePoint, Symbol

PROFILE = [
    ProfilePoint(0.0, 0.0), ProfilePoint(0.0, 25.0), ProfilePoint(120.0, 25.0),
    ProfilePoint(120.0, 45.0), ProfilePoint(200.0, 45.0), ProfilePoint(200.0, 20.0),
    ProfilePoint(300.0, 20.0), ProfilePoint(300.0, 0.0),
]


def _dim(symbol, value, uncertain=False):
    return Dimension(
        id=f"DIM-{symbol.value}-{value}", symbol=symbol, value=value,
        raw_text=f"{symbol.value}{value}", confidence=0.95,
        linked_element_id="X", is_uncertain=uncertain,
    )


def test_scale_one_to_one():
    dims = [_dim(Symbol.DIAMETER, 50), _dim(Symbol.DIAMETER, 90), _dim(Symbol.DIAMETER, 40),
            _dim(Symbol.LINEAR, 300)]
    profile, contradictions = solve_constraints(dims, PROFILE)
    assert [c for c in contradictions if c.severity == "error"] == []
    assert profile[1].r == 25.0  # unchanged scale


def test_sheet_scale_inferred_and_profile_normalized():
    # drawing plotted 1:2 — geometry is half the printed dimensions
    half_profile = [ProfilePoint(p.x / 2, p.r / 2) for p in PROFILE]
    dims = [_dim(Symbol.DIAMETER, 50), _dim(Symbol.DIAMETER, 90), _dim(Symbol.DIAMETER, 40)]
    profile, contradictions = solve_constraints(dims, half_profile)
    assert [c for c in contradictions if c.severity == "error"] == []
    assert profile[1].r == 25.0  # scaled back to true millimetres


def test_contradiction_reported_not_silently_fixed():
    dims = [_dim(Symbol.DIAMETER, 48)]  # no Ø48 surface exists
    _profile, contradictions = solve_constraints(dims, PROFILE)
    errors = [c for c in contradictions if c.severity == "error"]
    assert errors, "solver must report Ø48 vs actual surfaces"


def test_linear_contradiction_reported():
    dims = [_dim(Symbol.LINEAR, 301)]  # overall is 300
    _profile, contradictions = solve_constraints(dims, PROFILE)
    assert any(c.severity == "error" for c in contradictions)


def test_uncertain_dimension_skipped_with_warning():
    dims = [_dim(Symbol.DIAMETER, 48, uncertain=True)]
    _profile, contradictions = solve_constraints(dims, PROFILE)
    assert [c for c in contradictions if c.severity == "error"] == []
    assert any(c.severity == "warning" for c in contradictions)


def test_estimate_scale_public_api_matches_solve():
    from core.constraint_solver import estimate_scale
    from core.models import Dimension, Symbol

    profile = [
        ProfilePoint(0.0, 0.0), ProfilePoint(0.0, 12.5), ProfilePoint(50.0, 12.5),
        ProfilePoint(50.0, 22.5), ProfilePoint(90.0, 22.5), ProfilePoint(90.0, 10.0),
        ProfilePoint(150.0, 10.0), ProfilePoint(150.0, 0.0),
    ]
    def dim(text, symbol, value, uncertain=False):
        return Dimension(id=text, symbol=symbol, value=value, raw_text=text,
                        confidence=0.95, linked_element_id="x", is_uncertain=uncertain)

    dims = [dim("Ø25", Symbol.DIAMETER, 25.0), dim("Ø45", Symbol.DIAMETER, 45.0),
            dim("Ø20", Symbol.DIAMETER, 20.0)]
    assert estimate_scale(dims, profile) == 1.0
    # doubled prints on the sheet: true size is twice the plotted geometry
    dims2 = [dim("Ø50", Symbol.DIAMETER, 50.0), dim("Ø90", Symbol.DIAMETER, 90.0),
             dim("Ø40", Symbol.DIAMETER, 40.0)]
    assert estimate_scale(dims2, profile) == 2.0
    # half-size print (plotted 2:1)
    dims3 = [dim("Ø12.5", Symbol.DIAMETER, 12.5), dim("Ø22.5", Symbol.DIAMETER, 22.5)]
    assert estimate_scale(dims3, profile) == 0.5
    # degenerate input never crashes
    assert estimate_scale([], profile) == 1.0
    assert estimate_scale(dims, []) == 1.0
