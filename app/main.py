"""DrawToSTEP entry point.

GUI:      python -m app.main
Demo:     python -m app.main --demo
          Launches the app with the bundled example PDF pre-loaded (jury demo).
Headless: python -m app.main --headless path/to/drawing.pdf|scan.png [--out exports]
          Runs the full offline pipeline (parse → recognize → solve → build →
          export STEP+STL) and prints a summary. Used by tests, demos and CI.
Selftest: python -m app.main --selftest
          Builds the main window, prints SELFTEST OK and exits (CI smoke test).
Screenshot: python -m app.main --screenshot path.png
          Renders the main window to a PNG and exits (offscreen-friendly).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    # Windows code pages (cp1252/cp866) cannot encode the Russian UI/log text —
    # and a frozen windowed exe redirected via Start-Process inherits cp1252.
    # Never let a log line crash the pipeline: UTF-8 with replacement chars.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="DrawToSTEP — чертёж → STEP")
    parser.add_argument("--headless", metavar="DRAWING", default=None,
                        help="run the pipeline without the GUI and export STEP/STL "
                             "(vector PDF or scanned image .png/.jpg/.tif/.bmp)")
    parser.add_argument("--out", default="exports", help="output directory (default: exports/)")
    parser.add_argument("--demo", action="store_true",
                        help="launch the app with the bundled example PDF pre-loaded (jury demo)")
    parser.add_argument("--selftest", action="store_true",
                        help="build the main window, print SELFTEST OK and exit (CI smoke test)")
    parser.add_argument("--screenshot", metavar="PNG", default=None,
                        help="render the main window to a PNG and exit")
    args = parser.parse_args()

    if args.headless:
        return _headless(Path(args.headless), Path(args.out))
    if args.selftest:
        return _selftest()
    if args.screenshot:
        return _screenshot(Path(args.screenshot))

    demo_file = None
    if args.demo:
        from app.resources import demo_example_path
        demo_file = str(demo_example_path())

    from app.ui.main_window import main as gui_main
    return gui_main(demo_file=demo_file)


def _ci_report(kind: str, text: str) -> None:
    """Windowed (console=False) frozen builds have no reliable stdout on Windows,
    so CI smoke tests write a report file in the temp dir that the workflow
    dumps as annotations."""
    try:
        import os
        import tempfile
        with open(os.path.join(tempfile.gettempdir(), "drawtostep_ci_report.txt"), "a",
                  encoding="utf-8") as fh:
            fh.write(f"== {kind} ==\n{text}\n")
    except Exception:
        pass


def _selftest() -> int:
    """CI smoke test: construct the full window (no event loop)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication

        from app import theme
        from app.ui.main_window import MainWindow

        app = QApplication([])
        app.setApplicationName("DrawToSTEP")
        app.setStyleSheet(theme.stylesheet())
        window = MainWindow()
        assert window.stack.currentIndex() == 0, "upload screen must be first"
        window.show()
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        _ci_report("SELFTEST FAILED", tb)
        print(tb)
        return 1
    _ci_report("SELFTEST OK", "")
    print("SELFTEST OK")
    return 0


def _screenshot(out: Path) -> int:
    """Render the main window to a PNG (offscreen-friendly, used for docs)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app import theme
    from app.ui.main_window import MainWindow

    app = QApplication([])
    app.setApplicationName("DrawToSTEP")
    app.setStyleSheet(theme.stylesheet())
    theme.dot_grid_pixmap()
    window = MainWindow()
    window.resize(1240, 800)
    window.show()

    def _grab() -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(out))
        print(f"screenshot: {out}")
        app.quit()

    QTimer.singleShot(600, _grab)  # let the layout settle
    app.exec()
    return 0


def _headless(pdf: Path, out_dir: Path) -> int:
    from core.cad_builder import build_solid, export_step, export_stl
    from core.constraint_solver import (
        estimate_scale,
        scan_diameter_tol_mm,
        scan_linear_tol_mm,
        solve_constraints,
    )
    from core.ocr_gost import recognize_dimensions
    from core.pdf_parser import parse_pdf
    from core.scan_pipeline import _DEFAULT_DPI, parse_scan, read_dpi

    t0 = time.perf_counter()
    _ci_report("HEADLESS", f"start {pdf.name}")
    try:
        suffix = pdf.suffix.lower()
        is_scan = suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
        if is_scan:
            dpi = read_dpi(pdf) or _DEFAULT_DPI
            linear_tol: float | None = scan_linear_tol_mm(dpi)
            diameter_tol: float | None = scan_diameter_tol_mm(dpi)
            drawing = parse_scan(pdf)
        else:
            linear_tol = diameter_tol = None
            drawing = parse_pdf(pdf)
        _ci_report("HEADLESS", f"parsed: {len(drawing.profile)} profile pts")
        dimensions = recognize_dimensions(drawing)
        _ci_report("HEADLESS", f"recognized: {len(dimensions)} dims")
        profile, contradictions = solve_constraints(dimensions, drawing.profile,
                                                    bore_diameter=drawing.bore_diameter,
                                                    linear_tol_mm=linear_tol,
                                                    diameter_tol_mm=diameter_tol)
        _ci_report("HEADLESS", f"solved: {len(profile) if profile else 0} profile pts, "
                               f"{len(contradictions)} contradictions")
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        _ci_report("HEADLESS FAILED", tb)
        print(tb, file=sys.stderr)
        return 1
    if not profile:
        print("ERROR: не удалось распознать профиль детали вращения", file=sys.stderr)
        return 2
    unconfirmed = [d for d in dimensions if d.is_uncertain]
    print(f"Файл: {pdf.name}")
    print(f"Распознано размеров: {len(dimensions)} "
          f"(уверенных: {sum(1 for d in dimensions if not d.is_uncertain)}, "
          f"требуют проверки: {len(unconfirmed)})")
    for d in dimensions:
        flag = "НУЖЕН ВВОД" if d.is_uncertain else "ok"
        proposed = " [предложено по геометрии]" if d.proposed_by_geometry else ""
        print(f"  {d.label():<6} conf={d.confidence:.2f} {flag}  ({d.raw_text!r}){proposed}")
    for c in contradictions:
        print(f"  [{c.severity}] {c.message}")
    errors = [c for c in contradictions if c.severity == "error"]
    if errors:
        print("ERROR: есть противоречия — 3D не собрана", file=sys.stderr)
        return 3

    _ci_report("HEADLESS", "building solid")
    scale = estimate_scale(dimensions, drawing.profile, linear_tol_mm=linear_tol)
    bore_true = drawing.bore_diameter * scale if drawing.bore_diameter else None
    if scale != 1.0:
        print(f"Масштаб чертежа: {scale:.4g}× (геометрия масштабирована к истинным мм)")
    if bore_true:
        print(f"Отверстие: Ø{bore_true:.4g} мм (построено в 3D)")
    _ci_report("HEADLESS", "build_solid done")
    solid = build_solid(profile, dimensions, bore_diameter=bore_true)
    _ci_report("HEADLESS", "solid built")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf.stem
    step_path = export_step(solid, out_dir / f"{stem}.step")
    _ci_report("HEADLESS", "step exported")
    stl_path = export_stl(solid, out_dir / f"{stem}.stl")
    _ci_report("HEADLESS", "stl exported")
    elapsed = time.perf_counter() - t0
    print(f"STEP: {step_path}")
    print(f"STL:  {stl_path}")
    print(f"Объём: {solid.val().Volume():,.1f} мм³ · время парсинга+сборки: {elapsed * 1000:.0f} мс "
          f"(плюс время подтверждения размеров пользователем)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
