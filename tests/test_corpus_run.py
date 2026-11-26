"""Unit tests for the corpus runner's pure helpers (no pipeline execution).

The full pipeline + GT comparison is exercised end-to-end manually and in
nightly CI; here we only pin the deterministic pieces.
"""

from __future__ import annotations

import math

import pytest

from core.corpus_run import (
    STATUS_OK,
    _proper_rotations_24,
    normalize_error_signature,
    _signature_from_traceback,
)


def test_proper_rotations_are_24_proper_signed_permutations():
    mats = _proper_rotations_24()
    assert len(mats) == 24
    for m in mats:
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
               - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        assert det == 1
        # rows must be unit axis vectors
        for row in m:
            assert sorted(abs(v) for v in row) == [0, 0, 1]


def test_normalize_error_signature_strips_numbers_and_paths():
    sig = normalize_error_signature("ValueError", "bad value 123.45 in /home/user/x.pdf at line 42")
    assert sig == "ValueError: bad value # in <path> at line #"


def test_signature_from_traceback_extracts_exception():
    tb = "Traceback (most recent call last):\n  File \"a.py\", line 3, in f\n    boom\nValueError: expected 5 got 7\n"
    sig = _signature_from_traceback(tb)
    assert sig.startswith("ValueError")
    assert "#" in sig
    assert "7" not in sig


def test_signature_from_traceback_falls_back():
    assert _signature_from_traceback("").startswith("Crash")
    assert _signature_from_traceback("no exception line here").startswith("Crash")
