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

| Example | Plotted scale | Solved scale | Bore (drawn → true) | Volume, mm³ | Ground truth, mm³ | Δ |
|---|---|---|---|---|---|---|
| `shaft_3step_chamfer_bore.pdf` | 1:1 | 1.0 | Ø12 → Ø12 | 313,296.4 | 313,296.4 | +0.00 % |
| `flange_scale_1_2.pdf` | 1:2 | 2.0 | Ø20 → Ø40 | 197,920.1 | 197,920.3 | −0.00 % |
| `rotated_shaft.pdf` (view rotated, vertical axis) | 1:1 | 1.0 | — | 142,483.9 | 142,517.0 | −0.02 % |
| `bushing_2_1.pdf` | 2:1 | 0.5 | Ø24 → Ø12 | 5,026.5 | 5,026.5 | −0.00 % |
| `scan_test.png` (200 DPI, +2.5° deskewed, σ=16 noise) | 1:1 | 1.0 | Ø12.19 detected (conf 0.60) | 314,527.1 | 313,296.4 | +0.39 % |

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
- **scan_test.png**: geometry reconstruction is within +0.39 %. However,
  dimension linking on noisy scans is the weak link: only "240" reached
  conf 0.95; Ø/radius/chamfer callouts and chain lengths stayed at conf 0.60
  (uncertain). Uncertain dimensions are **never applied** without explicit
  user confirmation — 3D generation stays blocked in the UI until confirmed.
  The bore was detected at Ø12.19 (truth Ø12) but also arrives as uncertain.
- `scan_test.png` is not committed (6.3 MB binary); regenerate deterministically
  with `python data/examples/real/generate_real_examples.py` (seeded RNG,
  200 DPI, +2.5° rotation, Gaussian noise σ=16, slight blur).
- CadQuery/OpenCASCADE needs system GL libraries on Linux:
  `apt-get install -y libgl1 libglu1-mesa libegl1` (CI does this).
- Reproduce:
  ```bash
  python -m app.main --headless data/examples/real/shaft_3step_chamfer_bore.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/flange_scale_1_2.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/rotated_shaft.pdf --out /tmp/out
  python -m app.main --headless data/examples/real/bushing_2_1.pdf --out /tmp/out
  ```
