"""Fast offline end-to-end check on the committed synthetic goldens (Part 8).

Runs the real pipeline (parse_pdf → recognize_dimensions → solve_constraints
→ build_solid) on a small, fixed subset of the synthetic goldens and checks
the analytic ground truth: volume within 1% and exact bbox. CadQuery is a
hard dependency of the project, so no skip is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cad_builder import build_solid
from core.constraint_solver import solve_constraints
from core.ocr_gost import recognize_dimensions
from core.pdf_parser import parse_pdf

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus" / "golden"
SUBSET = ["golden_001", "golden_002", "golden_003", "golden_004", "golden_005"]


@pytest.mark.parametrize("stem", SUBSET)
def test_golden_pipeline_end_to_end(stem):
    pdf_path = GOLDEN_DIR / f"{stem}.pdf"
    gt = json.loads((GOLDEN_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    assert pdf_path.exists()

    drawing = parse_pdf(pdf_path)
    assert drawing.profile, "no revolution profile reconstructed"
    dimensions = recognize_dimensions(drawing)
    scaled, contradictions = solve_constraints(dimensions, drawing.profile)
    errors = [c for c in contradictions if c.severity == "error"]
    assert not errors, f"unexpected contradictions: {[c.message for c in errors]}"

    solid = build_solid(scaled, dimensions).val()
    assert abs(solid.Volume() - gt["expected"]["volume_mm3"]) / gt["expected"]["volume_mm3"] < 0.01
    bb = solid.BoundingBox()
    assert abs((bb.xmax - bb.xmin) - gt["expected"]["bbox_mm"]["length"]) < 1e-3
