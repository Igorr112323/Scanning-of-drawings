# BENCHMARK — real-output numbers / Замеры на реальных выходах

Every figure below was produced by the actual pipeline
(`python -m app.main --headless`, or `parse_scan` + `build_solid` for the scan),
not by hand-built models. Ground truth lives next to each example under
`data/examples/real/` (`*_ground_truth.json`); the examples themselves are
generated reproducibly by `data/examples/real/generate_real_examples.py`.

Все цифры получены прогоном реального конвейера (а не вручную собранными
моделями). Эталоны лежат рядом с примерами: `data/examples/real/*_ground_truth.json`;
сами примеры генерируются воспроизводимо скриптом
`data/examples/real/generate_real_examples.py`.

## Results / Результаты

| Example | Plotted scale | Solved scale | Bore (drawn → true) | Dimensions auto-linked | Uncertain | Volume, mm³ | Ground truth, mm³ | Δ |
|---|---|---|---|---|---|---|---|---|
| `shaft_3step_chamfer_bore.pdf` | 1:1 | 1.0 | Ø12 → Ø12 | 10/10 | 0 | 313,296.4 | 313,296.4 | +0.00 % |
| `flange_scale_1_2.pdf` | 1:2 | 2.0 | Ø20 → Ø40 | 3/3 | 0 | 197,920.1 | 197,920.3 | −0.00 % |
| `rotated_shaft.pdf` (view rotated, vertical axis) | 1:1 | 1.0 | — | 8/8 | 0 | 142,483.9 | 142,517.0 | −0.02 % |
| `bushing_2_1.pdf` | 2:1 | 0.5 | Ø24 → Ø12 | 3/3 | 0 | 5,026.5 | 5,026.5 | −0.00 % |
| `scan_test.png` (200 DPI, +2.5° deskewed, σ=16 noise) | 1:1 | 1.0 | Ø12.19 detected (conf 0.60) | 10/10 | 4 | 314,101.8 | 313,296.4 | +0.26 % |

Reference (synthetic, committed since v1): `flange_shaft_demo.pdf` headless →
volume 870,220.9 mm³ vs analytic π·(25²·120 + 45²·80 + 20²·100) = 870,221.2 mm³.

## Notes / Примечания

- **Scale inference is fully automatic** from GOST 2.302 scale votes; the
  printed `sheet.scale` field in generator GT is *not* used by the pipeline
  (it is not a reliable drawn→true multiplier).
- **rotated_shaft**: residual −0.02 % comes from the hemispherical cap being
  reconstructed as a 32-segment polyline instead of an exact spherical surface.
  All 8 printed dimensions (R12.5, 152.5, 62.5, 40, 50, Ø25/Ø50/Ø30) link with
  0 contradictions.
- **scan_test.png**: geometry reconstruction is within +0.26 % (volume
  314,101.8 vs 313,296.4, with both 2×45° chamfers and the Ø12.19 bore
  applied). Linking after the Phase 1.1 reclassification fix: **10/10
  auto-linked** (was 1/10). 6/10 arrive confident (≥ 0.85); **4/10 stay
  uncertain — all four are the zero-led Ø callouts** (`060/040/030/012`,
  RapidOCR drops the `Ø` glyph), linked to their leaders at confidence 0.80
  by design, never auto-applied, and resolved in the UI by clicking «Указать
  на чертеже» on the leader. Chain lengths 80/60/100 link to sequential
  segments of the merged dimension line (`L-0130#seg0/#seg1/#seg2`);
  chamfers → their leaders; 240 → the main length. Timing: ~5.2 s parse +
  OCR, solid at 13 ms. The bore was detected at Ø12.19 (truth Ø12) but also
  arrives as uncertain.
- **Scan solver tolerance**: raster binarisation erodes stroke endpoints by
  ~10 px per side (≈1.3 mm at 200 DPI) and the deskew cannot be sub-pixel,
  so absolute 0.05 mm checks block correct scans (measured gap up to 2.5 mm
  over 240 mm). The scan path therefore verifies lengths with
  `scan_linear_tol_mm(dpi) = max(0.05, 24 px)` (≈3.0 mm at 200 DPI) and
  diameters with `scan_diameter_tol_mm(dpi) = max(0.05, 4 px)` (≈0.51 mm).
  Vector PDFs keep the strict 0.05 mm. With the widened tolerance the scan
  reports **zero blocking contradictions** (only the four intended warnings,
  one per unconfirmed Ø).
- **RapidOCR on ×3-upscaled crops loses symbols** (measured): `Ø40` → `αAn`,
  `Ø30` → `U3U`, `240` → `24C`, `012` → empty. The pipeline therefore runs
  OCR on the full image; zero-led misreads are reported as uncertain and
  must be confirmed in the UI (click-to-link) — never silently applied.
  Symbol-level OCR accuracy on such scans is **not** production-grade yet;
  this is an honest limitation of the current release.
- `scan_test.png` is not committed (6.3 MB binary); regenerate deterministically
  with `python data/examples/real/generate_real_examples.py` (seeded RNG,
  200 DPI, +2.5° rotation, Gaussian noise σ=16, slight blur).
- CadQuery/OpenCASCADE needs system GL libraries on Linux:
  `apt-get install -y libgl1 libglu1-mesa libegl1` (CI does this).
- `data/examples/real/generate_real_examples.py` needs `matplotlib`,
  `reportlab` and `Pillow` (declared as the `examples` extra in
  `pyproject.toml`, plus in `requirements.txt`).
- Reproduce:
  ```bash
  python -m app.main --headless data/examples/real/shaft_3step_chamfer_bore.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/flange_scale_1_2.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/rotated_shaft.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/bushing_2_1.pdf --out /tmp/out
  ```
