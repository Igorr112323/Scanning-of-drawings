"""Resource path resolution for development and PyInstaller bundles."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Absolute path to a bundled resource.

    PyInstaller onefile unpacks data files under ``sys._MEIPASS``; in the
    source tree the repository root is two levels up from this file.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parents[1] / relative


def demo_example_path() -> Path:
    """The bundled flange demo used by --demo mode (and CI smoke tests)."""
    return resource_path("data/examples/flange_shaft_demo.pdf")
