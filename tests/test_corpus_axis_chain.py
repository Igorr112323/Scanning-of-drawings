"""Regression tests for the segmented dash-dot centre-line detector.

Root cause found on the real corpus (zenodo_open_mech pages): CAD->PDF
exporters draw centre lines as many separate thin segments with no dash
attribute on any segment, so the screen's dashed-line axis detector found
nothing (axis=0.000 on every page) and every page was NOT_SUPPORTED.

The fix (core/corpus_screen.classify_pdf, `_chain_axis`) detects the
collinear chain itself: >=4 pieces in one y band, gaps <= 8 mm, total span
>= 45% of page width, >=45% coverage. GOST dash-dot cadence is ~70-80%
coverage with 1.5-3 mm gaps.

Synthetic pages are generated with pymupdf at test time — no corpus files,
no file-specific special cases.
"""

from __future__ import annotations

import pytest

from core.corpus_screen import classify_file

PT_PER_MM = 72.0 / 25.4


def _make_shaft_pdf(path, with_axis=True, axis_gap_pt=8.0):
    """Dash-dot centre line exported as separate thin segments (x=40..760)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.draw_rect(fitz.Rect(80, 262, 720, 338), color=(0, 0, 0), width=1.4)
    if with_axis:
        x, i = 40.0, 0
        while x < 760.0:
            length = (60.0, 5.0)[i % 2]
            page.draw_line(fitz.Point(x, 300), fitz.Point(min(x + length, 760.0), 300),
                           color=(0, 0, 0), width=0.4)
            x += length + axis_gap_pt
            i += 1
    page.insert_text(fitz.Point(600, 120), "Ø120", fontsize=10)
    page.insert_text(fitz.Point(600, 150), "25", fontsize=10)
    doc.save(path)
    doc.close()


def test_segmented_centreline_is_detected(tmp_path):
    pdf = tmp_path / "shaft_chain.pdf"
    _make_shaft_pdf(pdf)
    ev = classify_file(pdf)
    assert ev.axis_score >= 0.6, ev.reason
    assert ev.symmetry_score >= 0.55, ev.reason
    assert ev.verdict == "BODY_OF_REVOLUTION", ev.reason


def test_no_centreline_stays_not_supported(tmp_path):
    pdf = tmp_path / "no_axis.pdf"
    _make_shaft_pdf(pdf, with_axis=False)
    ev = classify_file(pdf)
    assert ev.verdict != "BODY_OF_REVOLUTION"
    assert ev.axis_score < 0.6


def test_chain_with_huge_gaps_rejected(tmp_path):
    pdf = tmp_path / "gaps.pdf"
    _make_shaft_pdf(pdf, axis_gap_pt=90.0)  # ~32 mm gaps — not a GOST chain
    ev = classify_file(pdf)
    assert ev.axis_score < 0.6
