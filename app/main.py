"""DrawToSTEP entry point.

GUI:      python -m app.main
Headless: python -m app.main --headless path/to/drawing.pdf|scan.png [--out exports]
          Runs the full offline pipeline (parse → recognize → solve → build →
          export STEP+STL) and prints a summary. Used by tests, demos and CI.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="DrawToSTEP — чертёж → STEP")
    parser.add_argument("--headless", metavar="DRAWING", default=None,
                        help="run the pipeline without the GUI and export STEP/STL "
                             "(vector PDF or scanned image .png/.jpg/.tif/.bmp)")
    parser.add_argument("--out", default="exports", help="output directory (default: exports/)")
    args = parser.parse_args()

    if args.headless:
        return _headless(Path(args.headless), Path(args.out))

    from app.ui.main_window import main as gui_main
    return gui_main()


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
    dimensions = recognize_dimensions(drawing)
    profile, contradictions = solve_constraints(dimensions, drawing.profile,
                                                bore_diameter=drawing.bore_diameter,
                                                linear_tol_mm=linear_tol,
                                                diameter_tol_mm=diameter_tol)
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

    scale = estimate_scale(dimensions, drawing.profile, linear_tol_mm=linear_tol)
    bore_true = drawing.bore_diameter * scale if drawing.bore_diameter else None
    if scale != 1.0:
        print(f"Масштаб чертежа: {scale:.4g}× (геометрия масштабирована к истинным мм)")
    if bore_true:
        print(f"Отверстие: Ø{bore_true:.4g} мм (построено в 3D)")
    solid = build_solid(profile, dimensions, bore_diameter=bore_true)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf.stem
    step_path = export_step(solid, out_dir / f"{stem}.step")
    stl_path = export_stl(solid, out_dir / f"{stem}.stl")
    elapsed = time.perf_counter() - t0
    print(f"STEP: {step_path}")
    print(f"STL:  {stl_path}")
    print(f"Объём: {solid.val().Volume():,.1f} мм³ · время парсинга+сборки: {elapsed * 1000:.0f} мс "
          f"(плюс время подтверждения размеров пользователем)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
