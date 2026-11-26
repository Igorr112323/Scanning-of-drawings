"""CAD builder tests: build the demo shaft, export STEP/STL, re-import STEP."""

from __future__ import annotations

import math

import pytest

from core.cad_builder import build_solid, export_step, export_stl
from core.constraint_solver import solve_constraints
from core.models import ProfilePoint
from core.ocr_gost import recognize_dimensions
from core.pdf_parser import parse_pdf
from data.examples.generate_example import generate

# three cylinder surfaces: Ø50 x 120, Ø90 x 80, Ø40 x 100
EXPECTED_VOLUME = math.pi * (25.0**2 * 120.0 + 45.0**2 * 80.0 + 20.0**2 * 100.0)

SHAFT_PROFILE = [
    ProfilePoint(0.0, 0.0), ProfilePoint(0.0, 25.0), ProfilePoint(120.0, 25.0),
    ProfilePoint(120.0, 45.0), ProfilePoint(200.0, 45.0), ProfilePoint(200.0, 20.0),
    ProfilePoint(300.0, 20.0), ProfilePoint(300.0, 0.0),
]


def test_build_solid_volume():
    solid = build_solid(SHAFT_PROFILE)
    assert solid.val().Volume() == pytest.approx(EXPECTED_VOLUME, rel=1e-4)


def test_export_step_and_reimport(tmp_path):
    solid = build_solid(SHAFT_PROFILE)
    step = export_step(solid, tmp_path / "shaft.step")
    assert step.exists() and step.stat().st_size > 1_000

    import cadquery as cq
    reimported = cq.importers.importStep(str(step))
    assert reimported.val().Volume() == pytest.approx(EXPECTED_VOLUME, rel=1e-3)
    assert reimported.solids().vals()  # non-empty B-rep solid


def test_export_stl(tmp_path):
    solid = build_solid(SHAFT_PROFILE)
    stl = export_stl(solid, tmp_path / "shaft.stl")
    assert stl.exists() and stl.stat().st_size > 500


def test_bore_cut_reduces_volume():
    solid = build_solid(SHAFT_PROFILE, bore_diameter=20.0)
    bore_volume = math.pi * 10.0**2 * 300.0
    assert solid.val().Volume() == pytest.approx(EXPECTED_VOLUME - bore_volume, rel=1e-3)


def test_build_rejects_empty_profile():
    with pytest.raises(ValueError):
        build_solid([])


def test_full_pipeline_from_generated_pdf(tmp_path):
    pdf = tmp_path / "example.pdf"
    generate(pdf)
    drawing = parse_pdf(pdf)
    dims = recognize_dimensions(drawing)
    profile, contradictions = solve_constraints(dims, drawing.profile)
    assert [c for c in contradictions if c.severity == "error"] == []
    solid = build_solid(profile, dims)
    assert solid.val().Volume() == pytest.approx(EXPECTED_VOLUME, rel=1e-3)


def test_plain_rectangle_chamfered_ends_match_analytic():
    # plain rectangle half-profile, 45° chamfers on both outer corners
    profile = [
        ProfilePoint(0.0, 0.0), ProfilePoint(0.0, 30.0),
        ProfilePoint(150.0, 30.0), ProfilePoint(150.0, 0.0),
    ]
    leg = 2.0
    chamfer = math.pi * (30.0**2 * leg - (30.0**3 - 28.0**3) / 3.0)
    expected = math.pi * 30.0**2 * 150.0 - 2.0 * chamfer
    solid = build_solid(profile, chamfer_mm=leg)
    assert solid.val().Volume() == pytest.approx(expected, rel=1e-6)


def test_plain_rectangle_chamfered_ends_with_bore_match_analytic():
    profile = [
        ProfilePoint(0.0, 0.0), ProfilePoint(0.0, 30.0),
        ProfilePoint(150.0, 30.0), ProfilePoint(150.0, 0.0),
    ]
    leg = 2.0
    chamfer = math.pi * (30.0**2 * leg - (30.0**3 - 28.0**3) / 3.0)
    expected = (math.pi * 30.0**2 * 150.0 - 2.0 * chamfer
                - math.pi * 6.0**2 * 150.0)
    solid = build_solid(profile, bore_diameter=12.0, chamfer_mm=leg)
    assert solid.val().Volume() == pytest.approx(expected, rel=1e-6)
