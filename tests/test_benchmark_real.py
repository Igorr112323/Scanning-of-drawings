"""Real-scan benchmark harness — must work on ANY dropped scan.

Uses the committed generator to produce two different synthetic scans
(scan_test.png and the harsher scan_test_harsh.png, different rotation and
noise) to prove nothing is hardcoded. A real user scan goes through the exact
same code path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.benchmark_real import render_markdown, run_report

REAL_DIR = Path(__file__).resolve().parent.parent / "data" / "examples" / "real"
SCAN_GT = REAL_DIR / "scan_test_ground_truth.json"
HARSH = REAL_DIR / "scan_test_harsh.png"
HARSH_GT = REAL_DIR / "scan_test_harsh_ground_truth.json"


@pytest.fixture(scope="module", autouse=True)
def _generate_scans():
    from data.examples.real.generate_real_examples import gen_scan, gen_scan_harsh

    gen_scan()
    gen_scan_harsh()


def test_harness_on_reference_scan():
    report = run_report(REAL_DIR / "scan_test.png", gt_path=SCAN_GT)
    assert len(report.dimensions) == 10
    assert report.linked == 10
    assert report.proposed == 4            # Ø60/40/30/12 proposed from geometry
    assert report.volume_delta_pct is not None
    assert abs(report.volume_delta_pct) < 1.0
    md = render_markdown(report)
    assert "scan_test.png" in md
    assert "Распознано размеров" in md
    assert any("300 DPI" in w for w in report.warnings)  # 200 DPI < 300 → warning


def test_harness_on_different_scan_no_hardcoding():
    report = run_report(HARSH, gt_path=HARSH_GT)
    # nothing is hardcoded to scan_test.png: the harsh scan must also complete
    assert len(report.dimensions) >= 8
    assert report.linked >= 8
    assert report.volume_mm3 is not None
    assert abs(report.volume_delta_pct or 999.0) < 2.0   # harsh noise, wider bound
    md = render_markdown(report)
    assert "scan_test_harsh.png" in md


def test_report_marks_proposed_diameters():
    report = run_report(HARSH)
    proposed = [d for d in report.dimensions if d["proposed"]]
    assert {d["raw"] for d in proposed} == {"Ø60", "Ø40", "Ø30", "Ø12"}
    for d in proposed:
        assert d["uncertain"] is True


def test_low_dpi_warning_fires():
    report = run_report(REAL_DIR / "scan_test.png")  # 200 DPI
    assert any("Низкое качество скана" in w for w in report.warnings)


def test_harness_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        run_report(REAL_DIR / "does_not_exist.png")
