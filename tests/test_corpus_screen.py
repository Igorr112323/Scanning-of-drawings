"""Screening tests — evidence-based verdicts on the committed synthetic goldens."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from core.corpus_screen import classify_file, write_csv, summarize

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus" / "golden"
GOLDENS = sorted(GOLDEN_DIR.glob("golden_*.pdf"))


def test_goldens_present():
    assert len(GOLDENS) == 30


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.name)
def test_golden_is_body_of_revolution(path):
    ev = classify_file(path)
    assert ev.verdict == "BODY_OF_REVOLUTION", ev.reason
    assert ev.axis_score >= 0.6
    assert ev.symmetry_score >= 0.55
    assert ev.dia_count >= 1
    assert ev.text_layer


def test_blank_pdf_is_unreadable(tmp_path):
    import fitz

    blank = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=100)
    doc.save(blank)
    doc.close()
    ev = classify_file(blank)
    assert ev.verdict == "UNREADABLE"


def test_corrupt_file_is_unreadable(tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4 truncatedgarbage")
    ev = classify_file(junk)
    assert ev.verdict == "UNREADABLE"


def test_write_csv_and_summarize(tmp_path):
    rows = [classify_file(p) for p in GOLDENS[:3]]
    out = tmp_path / "screening.csv"
    write_csv(rows, out)
    with open(out, encoding="utf-8") as fh:
        table = list(csv.DictReader(fh))
    assert len(table) == 3
    assert {r["verdict"] for r in table} == {"BODY_OF_REVOLUTION"}
    summary = summarize(rows)
    assert "BODY_OF_REVOLUTION" in summary
