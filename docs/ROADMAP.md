# Roadmap / Дорожная карта

## Phase 1 — Foundation (this release)

- [x] Repository structure, packaging, CI (pytest + headless demo)
- [x] Core pipeline interfaces and dataclasses (`core/models.py`)
- [x] Vector-PDF parser: strokes (width/dash classification), GOST dash-dot axis,
      profile reconstruction for bodies of revolution
- [x] GOST dimension recognition (Ø/R/M/linear, OCR-confusable handling) with linking
- [x] Constraint solver: GOST 2.302 scale inference + contradiction reporting
- [x] CadQuery revolve builder + STEP/STL export (validated by re-import test)
- [x] iOS-minimal PySide6 shell: Upload / Processing / Verification / Viewer
- [x] Human-in-the-loop enforcement (yellow dimensions, gated 3D export)
- [x] Synthetic demo drawing generator (`data/examples/`)

## Phase 1.1 — Scans v1

- [ ] Wire `scan_preprocess` (deskew/binarize) into the upload path for raster files
- [ ] `vectorize` dash-dot grouping tuning on real scans
- [ ] DPI-aware mm calibration for scans (user-entered scale or A4/A3 size detection)
- [ ] Tesseract packaging for Windows .exe (vendored traineddata, GOST-compatible font)

## Phase 2 — Filed as GitHub Issues

- [ ] **Scan OCR pipeline** — production OCR for scanned ESKD sheets, traineddata handling
- [ ] **Prismatic parts** — plates/brackets: contour extraction, hole patterns, extrusion-based solids
- [ ] **Dataset collection** — 100+ flange/shaft drawings (synthetic generator + partner factory archive)
- [ ] **Neural segmentation** — YOLO/UNet lines vs dimensions vs hatch vs text (needs dataset first)
- [ ] **.exe packaging** — PyInstaller one-folder, offline assets, Windows installer
- [ ] Sections А–А and hidden lines (dash-dot-thin classification + cut solids)
- [ ] Conic chamfers / fillets recovery from arc segments (currently line-only parsing)
- [ ] Thread modelling (M-dims → helical feature + cosmetic thread in STEP)
- [ ] Roughness / tolerances / PMI transfer to the model
- [ ] Batch mode: folder of PDFs → folder of STEP files

## Phase 3 — Polish & hardening

- [ ] QThread worker for large PDFs (UI currently synchronous; fine < 2 s)
- [ ] Undo/redo of dimension edits, keyboard-first verification flow
- [ ] Real GOST title-block parsing (drawing number → filename of exported STEP)
- [ ] Localization: full RU/EN toggle
- [ ] Crash reporting OFF by default (offline promise); local log file only

## Success criteria

| Metric | Target | Current |
|---|---|---|
| Generation time (vs ~25 min manual) | < 1 s | ~30 ms + human verification |
| Dimension accuracy after solve | 0.01 mm | exact match on synthetic example (rel. err < 1e-3 on volume) |
| Hallucinated dimensions | 0 | 0 — unverified dimensions block export by construction |
