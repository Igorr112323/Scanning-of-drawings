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
| Dimension unparseable | yellow row, value editable, 3D blocked |
| Contradictory diameters | red banner, 3D blocked, nothing silently "fixed" |
| Scanned image opened | friendly v1.1 notice (OpenCV path not wired yet) |
| Libre/duplicate chain dims | both reported; solver validates each |

## Performance

Vector PDF → solid: ~30 ms on the demo example (parse+solve+revolve). Rendering is one-shot;
no GPU required.

## Packaging (Phase 2)

PyInstaller one-folder build (`pyinstaller --noconfirm app/main.py`) after Phase 2 issues land;
UI already avoids network and temp files outside standard paths.
