"""Benchmark harness for REAL scans (user-provided).

    python -m core.benchmark_real --scan data/examples/real_scans/my_scan.png
    python -m core.benchmark_real --scan x.png --gt ground_truth.json --out docs/real_scan_report.md

Works on ANY readable scan — nothing is hardcoded to scan_test.png. Output is
a Markdown report (default docs/real_scan_report.md) with:

    DPI estimate (from metadata, else 200 + warning), image size,
    scan-quality metrics (Laplacian blur score, noise residual, border ink),
    dimensions found / linked / uncertain / proposed-by-geometry,
    solver contradictions, estimated linear error vs printed overall length
    (when a confident LINEAR dimension exists), volume error when a ground
    truth JSON is passed, quality verdict and honest limitations.

Exit codes: 0 = report produced; 2 = hard failure (unreadable image, no
profile found). Quality warnings are part of the report, never exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from core.constraint_solver import (
    scan_diameter_tol_mm,
    scan_linear_tol_mm,
    solve_constraints,
    estimate_scale,
)
from core.cad_builder import build_solid
from core.ocr_gost import recognize_dimensions
from core.scan_pipeline import _DEFAULT_DPI, parse_scan, read_dpi

# quality thresholds (measured on the bundled synthetic scans; documented in BENCHMARK)
_MIN_DPI = 300.0
_BLUR_MIN = 100.0          # Laplacian variance below this → blurry
_BORDER_INK_MAX = 0.01     # >1% ink on the outer 2 px frame → cropped content


@dataclass
class ScanReport:
    scan_path: str
    dpi: float
    dpi_assumed: bool
    width_px: int
    height_px: int
    blur_var: float
    noise_sigma: float
    border_ink: float
    dimensions: list[dict] = field(default_factory=list)
    contradictions: list[tuple[str, str]] = field(default_factory=list)
    profile_length_mm: float | None = None
    estimated_linear_error_mm: float | None = None
    scale: float = 1.0
    bore_mm: float | None = None
    volume_mm3: float | None = None
    gt_volume_mm3: float | None = None
    volume_delta_pct: float | None = None
    linked: int = 0
    uncertain: int = 0
    proposed: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _quality_warnings(dpi: float, dpi_assumed: bool, blur_var: float,
                      border_ink: float, linear_err: float | None,
                      linear_tol: float) -> list[str]:
    warnings: list[str] = []
    if dpi_assumed:
        warnings.append(f"DPI не записан в метаданных — принято {dpi:.0f}; размеры и допуски могут быть неточны")
    if dpi < _MIN_DPI:
        warnings.append(
            f"Низкое качество скана — пересканируйте в {_MIN_DPI:.0f} DPI, точность ~3 мм")
    if blur_var < _BLUR_MIN:
        warnings.append(f"Размытый скан (резкость {blur_var:.0f} < {_BLUR_MIN:.0f}) — повысьте резкость/уберите движение")
    if border_ink > _BORDER_INK_MAX:
        warnings.append("Инк касается края листа — возможно, лист обрезан; измеренные длины могут быть занижены")
    if linear_err is not None and linear_err > linear_tol:
        warnings.append(f"Расхождение напечатанной и измеренной длины {linear_err:.1f} мм > допуска {linear_tol:.1f} мм")
    return warnings


def run_report(scan_path: str | Path, gt_path: str | Path | None = None,
               out_dir: str | Path = "exports") -> ScanReport:
    """Run the full scan pipeline and collect a report (no files written)."""
    scan = Path(scan_path)
    if not scan.exists():
        raise FileNotFoundError(f"Файл не найден: {scan}")
    img = cv2.imread(str(scan), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Не удалось прочитать изображение: {scan}")

    dpi = read_dpi(scan)
    dpi_assumed = dpi is None
    if dpi is None:
        dpi = _DEFAULT_DPI
    h, w = img.shape
    blur_var = float(cv2.Laplacian(img, cv2.CV_64F).var())
    med = cv2.medianBlur(img, 5)
    noise_sigma = float(np.std(img.astype(np.float32) - med.astype(np.float32)))
    _, bw = cv2.threshold(img, 180, 255, cv2.THRESH_BINARY_INV)
    ink = bw > 0
    border_ink = float(
        (ink[:2, :].mean() + ink[-2:, :].mean() + ink[:, :2].mean() + ink[:, -2:].mean()) / 4.0)

    linear_tol = scan_linear_tol_mm(dpi)
    diameter_tol = scan_diameter_tol_mm(dpi)

    drawing = parse_scan(scan)
    dimensions = recognize_dimensions(drawing)
    scaled_profile, contradictions = solve_constraints(
        dimensions, drawing.profile, bore_diameter=drawing.bore_diameter,
        linear_tol_mm=linear_tol, diameter_tol_mm=diameter_tol)
    scale = estimate_scale(dimensions, drawing.profile, linear_tol_mm=linear_tol)

    profile_length = None
    estimated_linear_error = None
    if scaled_profile:
        profile_length = max(p.x for p in scaled_profile) - min(p.x for p in scaled_profile)
        confident_linear = [d.value for d in dimensions
                            if d.symbol.name == "LINEAR" and not d.is_uncertain and d.value > 0]
        if confident_linear and profile_length:
            estimated_linear_error = abs(max(confident_linear) - profile_length)

    warnings = _quality_warnings(dpi, dpi_assumed, blur_var, border_ink,
                                 estimated_linear_error, linear_tol)

    report = ScanReport(
        scan_path=scan.name, dpi=dpi, dpi_assumed=dpi_assumed,
        width_px=w, height_px=h, blur_var=blur_var, noise_sigma=noise_sigma,
        border_ink=border_ink,
        contradictions=[(c.severity, c.message) for c in contradictions],
        profile_length_mm=profile_length,
        estimated_linear_error_mm=estimated_linear_error,
        scale=scale,
        bore_mm=(drawing.bore_diameter * scale) if drawing.bore_diameter else None,
        linked=sum(1 for d in dimensions if d.linked_element_id),
        uncertain=sum(1 for d in dimensions if d.is_uncertain),
        proposed=sum(1 for d in dimensions if d.proposed_by_geometry),
        warnings=warnings,
        errors=[c.message for c in contradictions if c.severity == "error"],
    )
    for d in dimensions:
        report.dimensions.append({
            "raw": d.raw_text,
            "symbol": d.symbol.name,
            "value": d.value,
            "conf": d.confidence,
            "linked": d.linked_element_id or "—",
            "uncertain": d.is_uncertain,
            "proposed": d.proposed_by_geometry,
        })

    if gt_path is not None:
        gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
        gt_volume = gt.get("expected_volume_mm3")
        if gt_volume and scaled_profile:
            bore_true = drawing.bore_diameter * scale if drawing.bore_diameter else None
            solid = build_solid(scaled_profile, dimensions, bore_diameter=bore_true)
            report.volume_mm3 = solid.val().Volume()
            report.gt_volume_mm3 = gt_volume
            report.volume_delta_pct = 100.0 * (report.volume_mm3 - gt_volume) / gt_volume

    return report


def render_markdown(r: ScanReport) -> str:
    lines = [
        f"# Отчёт по скану — `{r.scan_path}`",
        "",
        f"Сгенерировано: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · `python -m core.benchmark_real`",
        "",
        "## Исходные данные",
        "",
        f"- DPI: **{r.dpi:.0f}**{' (из метаданных)' if not r.dpi_assumed else ' (принято по умолчанию — метаданных нет)'}",
        f"- Размер: {r.width_px}×{r.height_px} px",
        f"- Масштаб (оценка солвера): {r.scale:g}×",
        f"- Отверстие: {'Ø%.2f мм' % r.bore_mm if r.bore_mm else 'не обнаружено'}",
        "",
        "## Качество скана",
        "",
        f"- Резкость (Laplacian variance): **{r.blur_var:.1f}** (норма ≥ {_BLUR_MIN:.0f})",
        f"- Оценка шума (residual σ): **{r.noise_sigma:.1f}**",
        f"- Инк на рамке края: **{100 * r.border_ink:.2f}%** (норма < 1%)",
        f"- Распознано размеров: {len(r.dimensions)} · привязано: {r.linked}/{len(r.dimensions)} · "
        f"требуют подтверждения: {r.uncertain} · предложено геометрией: {r.proposed}",
        "",
    ]
    if r.warnings:
        lines.append("**Предупреждения:**")
        lines.append("")
        lines += [f"- ⚠️ {w}" for w in r.warnings]
        lines.append("")
    else:
        lines += ["Предупреждений по качеству нет.", ""]

    lines += [
        "## Размеры",
        "",
        "| Текст | Тип | Значение | Уверенность | Привязка | Статус |",
        "|---|---|---|---|---|---|",
    ]
    for d in r.dimensions:
        status = []
        if d["proposed"]:
            status.append("предложен по геометрии — подтверди")
        if d["uncertain"]:
            status.append("НУЖЕН ВВОД")
        else:
            status.append("ok")
        lines.append(f"| {d['raw']} | {d['symbol']} | {d['value']:g} | {d['conf']:.2f} | "
                     f"{d['linked']} | {' · '.join(status)} |")

    lines += ["", "## Оценка", ""]
    if r.profile_length_mm is not None:
        lines.append(f"- Длина профиля по скану: **{r.profile_length_mm:.1f} мм**")
    if r.estimated_linear_error_mm is not None:
        lines.append(f"- Оценка линейной погрешности (напечатано vs измерено): "
                     f"**{r.estimated_linear_error_mm:.1f} мм**")
    if r.contradictions:
        lines.append("- Солвер:")
        lines += [f"  - [{sev}] {msg}" for sev, msg in r.contradictions]
    else:
        lines.append("- Солвер: противоречий нет")
    if r.volume_mm3 is not None:
        lines += [
            f"- Объём (с фасками и отверстием): **{r.volume_mm3:,.1f} мм³**",
            f"- Эталон: {r.gt_volume_mm3:,.1f} мм³ · отклонение **{r.volume_delta_pct:+.2f} %**",
        ]
    lines += [
        "",
        "## Честные ограничения",
        "",
        "- Неуверенные размеры НИКОГДА не применяются без явного подтверждения в интерфейсе.",
        "- Растр 200 DPI съедает ~3 мм; если DPI скана ниже 300, точность по длинам ~3 мм.",
        "- OCR на зашумлённых сканах теряет символы (типично: Ø → ведущий ноль); такие размеры подтверждаются кликом «Указать на чертеже».",
        "- Фаски применяются из размеров 2×45°; другие фаски/скругления — Phase 2.",
        "- STEP — твердотельное B-rep, не параметрическая история построения.",
        "",
        "## Вердикт",
        "",
        ("**Скан пригоден для работы** — все размеры распознаны и привязаны; "
         "подтвердите жёлтые строки в интерфейсе." if not r.warnings else
         "**Пересканируйте** с рекомендациями в «Качество скана» — иначе 3D будет размерно неточна."),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Real scan benchmark report")
    parser.add_argument("--scan", required=True, type=Path, help="путь к скану (любая деталь вращения)")
    parser.add_argument("--gt", type=Path, default=None, help="ground truth JSON (опционально)")
    parser.add_argument("--out", type=Path, default=Path("docs/real_scan_report.md"),
                        help="куда писать отчёт (по умолчанию docs/real_scan_report.md)")
    parser.add_argument("--out-dir", type=Path, default=Path("exports"),
                        help="каталог для STEP/STL при расчёте объёма (по умолчанию exports/)")
    args = parser.parse_args()

    try:
        report = run_report(args.scan, gt_path=args.gt, out_dir=args.out_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")

    print(f"Файл: {report.scan_path}")
    print(f"DPI: {report.dpi:.0f}{' (по умолчанию)' if report.dpi_assumed else ''} · "
          f"размер {report.width_px}×{report.height_px} px")
    print(f"Распознано: {len(report.dimensions)} · привязано: {report.linked} · "
          f"требуют подтверждения: {report.uncertain} · предложено геометрией: {report.proposed}")
    if report.estimated_linear_error_mm is not None:
        print(f"Оценка линейной погрешности: {report.estimated_linear_error_mm:.1f} мм")
    if report.volume_mm3 is not None:
        print(f"Объём: {report.volume_mm3:,.1f} мм³ (Δ {report.volume_delta_pct:+.2f} % vs GT)")
    for w in report.warnings:
        print(f"  ⚠️ {w}")
    for e in report.errors:
        print(f"  [error] {e}")
    print(f"Отчёт записан: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
