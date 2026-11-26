# Architecture / Архитектура

## Pipeline

```
                    ┌────────────────────────────── offline ──────────────────────────────┐
                    │                                                                     │
  vector PDF ──────►│  pdf_parser ──► recognize_dimensions ──► solve_constraints          │
  (KOMPAS/CAD)      │  (PyMuPDF)     (ocr_gost.py)             (constraint_solver.py)     │
                    │                    │                             │                   │
  scan/raster ─────►│  scan_preprocess ──► vectorize ──► ocr_words ──┘                    │
  (Phase 1.1)       │  (OpenCV)         (hough/grouping)  (pytesseract, optional)        │
                    │                                                                     │
                    │        Drawing + Dimension[] (+ profile, contradictions)             │
                    │                       ▼                                             │
                    │   ┌──────────── HUMAN-IN-THE-LOOP (verification screen) ──────────┐ │
                    │   │  uncertain (conf<0.85 | unlinked) → yellow → edit + confirm   │ │
                    │   │  every dimension confirmed  ⇒  build allowed                 │ │
                    │   └───────────────────────────┬──────────────────────────────────┘ │
                    │                               ▼                                     │
                    │   build_solid (CadQuery Revolve) ──► export STEP / STL              │
                    │                                                                     │
                    └─────────────────────────────────────────────────────────────────────┘
```

## Module contracts (stable interfaces, `core/`)

| Function | Input | Output |
|---|---|---|
| `parse_pdf(path)` | vector PDF path | `Drawing` (elements + profile + views) |
| `preprocess_scan(image)` | BGR/gray ndarray | binarized ndarray |
| `vectorize(cleaned)` | ndarray | `list[VectorElement]` (CONTOUR/DIMENSION_LINE/AXIS/HATCH/TEXT) |
| `recognize_dimensions(drawing)` | `Drawing` | `list[Dimension]` |
| `solve_constraints(dimensions, profile)` | inputs | `(scaled_profile, list[Contradiction])` |
| `build_solid(profile, dimensions, bore_diameter=None)` | mm points | `cq.Workplane` with one solid |
| `export_step(shape, path)` / `export_stl(shape, path)` | solid | file on disk |

`models.py` holds the dataclasses; nothing else carries state between stages.

## Scan path (Phase 1.1 · implemented)

```
scan_test.png ─► scan_preprocess ─► vectorize ─► ocr_words (RapidOCR, full image)
                     │                  │            (3×-upscaled crops were
                     │                  │             measured to misread more —
                     │                  │             see docs/BENCHMARK.md)
                 binarized          elements      texts
                              │
                              ▼
        scan_linking.reclassify_thin_strokes   (thin 2-pt strokes whose
                              │                 cross-width collapses AND that
                              │                 align with an OCR text anchor
                              │                 → DIMENSION_LINE; CONTOUR and
                              │                 AXIS never reclassified)
                              ▼
             recognize_dimensions ─► constraint_solver ─► build_solid
```

1. **Reclassification (mandatory).** Strokes reclassified to `DIMENSION_LINE` must be
   thin (≤ 6 px at 200 DPI), non-horizontal or collinear with a text anchor, and pass a
   min-of-5 thickness probe (min over endpoint probes, not the junction-inflated mean).
   Thick revolution outlines are never reclassified — they stay `CONTOUR`; the centerline
   stays `AXIS`.
2. **OCR → dimension** is the same regex fallback as the PDF path; unparseable texts are
   reported as uncertain (value 0.0), never dropped.
3. **Linking is per OCR text**, not per stroke: anchor = text bbox centre.
   - DIAMETER: rank candidates by |dx| primarily (Ø leaders are vertical);
     zero-led RapidOCR misreads (`060` → `Ø60`) are confidence-capped at 0.80 when
     linked — never auto-applied, always shown for confirmation.
   - LINEAR chain dimensions: horizontal same-row `DIMENSION_LINE` fragments are merged
     into logical row intervals, cut at the midpoints between consecutive text centres
     (`#seg0`, `#seg1`, …). Each chain dim links to its own segment
     (80/60/100 → `#seg0…#seg2`), not to the whole stroke or to a neighbour's segment.
   - LINEAR far links (> 5 mm) with `arrow_end=True` score 0.95, else 0.90.
4. **Click-to-link (mandatory human-in-the-loop).** In the verification screen every
   uncertain row offers «Указать на чертеже»: the preview switches to crosshair mode and
   the user clicks the intended stroke. `core.scan_linking.nearest_vector_element`
   (point → nearest stroked `VectorElement`, max radius 15 mm, TEXT ignored) picks the
   element; `confirm_dimension_link` flips the row to confidence 1.0 / linked /
   not-uncertain. A green mark is drawn on the preview; `Esc` cancels; «Перепривязать»
   re-enters link mode to fix a wrong pick. «Подтвердить и собрать 3D» stays disabled
   until every dimension is auto-linked with confidence ≥ 0.85, manually linked, or
   explicitly confirmed — the gate itself is unchanged.
5. **Scan solver tolerance.** Vector PDFs verify at 0.05 mm; raster scans pass
   pixel-derived overrides (`scan_linear_tol_mm` = max(0.05, 24 px), ≈3 mm at 200 DPI;
   `scan_diameter_tol_mm` = max(0.05, 4 px), ≈0.51 mm) because binarisation erodes stroke
   endpoints ~10 px per side. Diameters on scans are all uncertain (zero-led OCR) and are
   excluded from solving; LINEARs are then checked with the widened tolerance — zero
   blocking contradictions on the reference scan.
6. **Scans in the app.** Dropping a `.png/.jpg/.tif/.bmp` on the upload area runs the
   scan pipeline in a `QThread` (`ScanWorker`) while the Processing screen animates; the
   Verification screen is populated only when OCR finishes (never half-filled). The headless
   entry point accepts the same files (`--headless scan_test.png`) with the same tolerances.
7. **Ø recovery via geometry (propose, never auto-apply).** RapidOCR drops the Ø glyph
   ("Ø60" → "060"). `core.diameter_recovery.propose_geometry_bound_diameters` cross-checks
   the printed number against axis-referenced stroke measurements and the extracted profile:
   if it matches a measured diameter (outer surface or bore inner walls) within
   `max(0.75 mm, 2 %)`, the dimension is re-emitted as `Ø<value>` with **confidence 0.85,
   `is_uncertain = True`, `proposed_by_geometry = True`** — the Verification row pre-fills
   `Ø<value>` and shows «предложено по геометрии — подтверди»; the user confirms with ONE
   click. Mismatch (e.g. geometry 55 vs printed 060) proposes nothing and the row stays
   uncertain. Idempotent. Never auto-applied — the 3D gate is unchanged.
8. **Real-scan harness.** `python -m core.benchmark_real --scan file.png [--gt gt.json]`
   produces a Markdown report (default `docs/real_scan_report.md`): DPI (metadata or assumed
   200 + warning), blur/noise/border-ink metrics, dims found/linked/uncertain/proposed,
   solver contradictions, estimated linear error, volume vs GT, verdict. Works on any scan —
   see `data/examples/real_scans/README_RU.md` for how to scan correctly. Quality below
   threshold (DPI < 300 or linear error > tolerance) shows an orange banner in Verification:
   «Низкое качество скана — пересканируйте в 300 DPI, точность ~3 мм».
9. **Bundle & demo mode.** `DrawToSTEP.spec` (PyInstaller onefile) bundles PySide6,
   CadQuery/OCP, OpenCV, RapidOCR (ONNX models) + the demo PDF and a regenerated scan example;
   `.github/workflows/build-exe.yml` builds on `windows-latest` on release/dispatch, smoke-tests
   (`--selftest` offscreen + `--headless` STEP build of the demo PDF), uploads the artifact and
   attaches it to the GitHub Release. `--demo` launches with the bundled flange example
   pre-loaded (skips the file dialog); `--selftest`/`--screenshot` are CI smoke flags.

## How the v1 parser works

1. `page.get_drawings()` → every stroked path with width + dash pattern.
   Filled-only paths (dimension arrowheads, hatch fills) are ignored.
2. Classification of strokes:
   - `width ≥ 1.2 pt` → **CONTOUR** (GOST main line);
   - `width < 1.2 pt`, dashed pattern + horizontal → **AXIS** (GOST dash-dot centre line);
   - otherwise thin solid → **DIMENSION_LINE** (dimension/extension lines, leaders).
3. `page.get_text("words")` → text words with bounding boxes (exact, no OCR).
4. Text → dimension: regex `^(Ø|⌀|∅|Φ|%%c|R|M)?\s*<number>…`; strict match → confidence 0.95,
   OCR-confusable-resolved (O→0, I→1…) → ≤ 0.7, unparseable but dimension-looking → reported
   as uncertain with value 0.0 (never silently dropped).
5. Linking: every dimension is linked to the nearest CONTOUR/DIMENSION_LINE/AXIS element
   within 9 mm of its anchor. Unlinked ⇒ confidence capped at 0.6 and `is_uncertain=True`.
6. Profile: strictly-horizontal CONTOUR segments above the axis give the step surfaces
   (`r = axis_y − y`); the x-range is split at breakpoints and each elementary interval must be
   covered by exactly one surface — gaps or conflicting radii ⇒ empty profile (we refuse to guess).

## Constraint solver: scale inference

GOST drawings are plotted at scale. The solver restricts itself to the GOST 2.302 series
(0.02 … 50.0) and picks the scale that satisfies the most DIAMETER/LINEAR dimensions
(ties → 1:1). It then verifies every non-uncertain dimension against the scaled profile
and reports contradictions — it never edits dimension values. Uncertain dimensions are
excluded from solving and surfaced as warnings.

## Human-in-the-loop (mandatory)

`is_uncertain` ⇔ `confidence < 0.85` or `linked_element_id is None`.
The verification screen renders those rows in yellow (#FFF3B0 / #FFCC00) with an editable
field; the "Подтвердить и собрать 3D" button stays disabled until every row is confirmed
and no `severity="error"` contradiction exists. `build_from_drawing` re-checks this in code.

## UI

PySide6, `QStackedWidget` with 4 screens (Upload → Processing → Verification → Viewer),
floating pill toolbars (back circle top-left, share/more top-right, bottom navigation),
dotted Freeform-style background, white 24 px cards. Icons are painted with QPainter
(no icon-font dependency). 3D preview is a software-rendered wireframe (rings + generators);
it shows exactly the exported geometry and needs no OpenGL.

## Failure modes & honesty guarantees

| Situation | Behaviour |
|---|---|
| PDF has no axis / not a body of revolution | empty profile → error surfaced, no 3D |
| Ø read with dropped leading zero/glyph (060, 012…) | linked, confidence capped at 0.80 → always shown for confirmation |
| Dimension unparseable | yellow row, value editable, 3D blocked |
| Dimension linked to the wrong stroke by the user | undo: click «Указать на чертеже» again and pick the right one |
| Contradictory diameters | red banner, 3D blocked, nothing silently "fixed" |
| Scanned image opened | OpenCV pipeline runs end-to-end (preprocess → vectorize → OCR → link) |
| Libre/duplicate chain dims | both reported; solver validates each |

## Performance

Vector PDF → solid: ~30 ms on the demo example (parse+solve+revolve). Rendering is one-shot;
no GPU required.

## Packaging

PyInstaller onefile (`DrawToSTEP.spec`; build config in `.github/workflows/build-exe.yml`,
Windows x64). UI avoids network and temp files outside standard paths; bundled examples live
under `data/` via `sys._MEIPASS` (see `app/resources.py`).
