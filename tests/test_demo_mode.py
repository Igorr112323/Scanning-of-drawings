"""--demo mode: the app launches with the bundled flange example pre-loaded.

Offscreen Qt platform; no display required. Runs the same code path as
`python -m app.main --demo`: MainWindow(demo_file=...) → processing →
verification with the 7 known dimensions.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 not importable")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_demo_example_bundled():
    from app.resources import demo_example_path

    path = demo_example_path()
    assert path.exists(), f"bundled demo example missing: {path}"
    assert path.suffix == ".pdf"


def test_demo_mode_preloads_verification(qapp):
    from app import theme
    from app.resources import demo_example_path
    from app.ui.main_window import MainWindow

    theme.dot_grid_pixmap()
    window = MainWindow(demo_file=str(demo_example_path()))
    window.show()

    deadline = time.time() + 20.0
    while time.time() < deadline:
        qapp.processEvents()
        if window.stack.currentIndex() == 2 and window.verification_screen.rows:
            break
        time.sleep(0.05)
    qapp.processEvents()

    assert window.stack.currentIndex() == 2, "demo must land on the verification screen"
    assert len(window.verification_screen.rows) == 7
    assert window.verification_screen.build_button.isEnabled()

    # and the full build works from the demo state
    window._on_build_requested(window.verification_screen.dimensions())
    qapp.processEvents()
    assert window._pipeline_result.get("volume_mm3") == pytest.approx(
        870_220.9, rel=0.01)
