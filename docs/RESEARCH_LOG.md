# RESEARCH_LOG — real-corpus benchmark program (drawings → STEP)

> **Status: honest, in-progress.** This document replaces an earlier uncommitted
> draft that was lost in a workspace reset (2026-11-26). Every metric below names
> its run/commit and carries its denominator. Anything not measured is written
> "NOT MEASURED" — never implied.
>
> **Superseded rows are labelled with the commit that produced them.** Where the
> latest push (`b8d1f99`) is expected to change a number, the old value is kept
> and marked `(pre-b8d1f99)` until the new run reports.

## 0. Goal and non-negotiables

Measure the revolution-only pipeline on **real, openly licensed engineering
drawings** and report numbers with denominators:

1. Every figure is computed from committed/CI-verified data (`data/corpus/*`,
   CI job annotations). No hand-typed corpus numbers.
2. jcrzd/ecado (no license metadata) are used for **aggregate, internal
   evaluation metrics only** — per-file rows are never published, logged, cited
   or committed. Zenodo 24167336 (CC BY 4.0) rows are citable with attribution.
3. No fixture special-casing: corpus ids never appear in pipeline/screen logic.
4. Real evidence only — if the pipeline produced nothing, the log says so.
5. PRs #7/#8/#9 stay open and unmerged until explicitly reviewed.

## 1. Environment reality (verified)

- Build sandbox egress: only `github.com`, `codeload.github.com`, `api.github.com`,
  `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org` open.
  `zenodo.org`, `huggingface.co` — TLS reset (verified). Blob/log hosts
  (`*.blob.core.windows.net`, results-receiver) — EOF. Artifacts therefore cannot
  be pulled into the sandbox; **GitHub Actions is the executor**, and
  `api.github.com` check-run/check-suite annotations are the evidence channel.
- `.github/workflows/corpus-nightly.yml` runs on schedule, `workflow_dispatch`,
  and a temporary `push: [feat/corpus-1000]` trigger (auto-runs the corpus on
  every push; **to be removed after the corpus PR merges**).
- `actions/cache` carries `data/corpus/` across runs; push runs force a fresh
  `results.jsonl` (`--no-resume`) so every push re-measures end-to-end.
- GitHub caps check-run annotation **messages** at ~4096 bytes **and stores at
  most ~10 annotations per check-run** — the rest are silently dropped. Evidence
  notices are therefore **chunked** (`-2`, `-3`…) and emitted in priority order;
  a single >3.4 KB annotation is hard-split. Verified: the b713040 run lost
  every annotation after the 10th (CORPUS-SUMMARY, ZENODO-EVIDENCE, the PDF
  diagnostics chunk ≥2) — fixed by the prioritized 7–8-annotation layout.

## 2. Data sources (see `docs/DATA_SOURCES.md`)

| source | files (limit 40) | license | use |
|---|---|---|---|
| zenodo 24167336 "100 2D orthographic drawings.pdf" (+1 title-like file) | 42 | CC BY 4.0 | per-file evidence OK |
| hf jcrzd/engineering-drawings (JPGs, UNSW-style sheets) | 40 | **unresolved — internal only** | aggregates only |
| hf ecado/rfq-engineering-drawings | 0 (not in this run) | unresolved — internal only | not evaluated |

Zenodo files screen: 41 pages (`page_001..page_041`) + 1 title-like PDF
(`1- 100 2D orthographic drawings.pdf`). jcrzd: JPGs (raster path).

## 3. Phases and findings

### Phase 0 — dataset registry / fetch / manifest join — DONE

`core/dataset_fetch.py` (`hf_list_files` with Link-header pagination after the
initial flat-API approach broke), `manifest.jsonl` keyed by path; gt_3d matched by
path **stem** (`dc6d2c1`). Golden fixtures excluded from corpus metrics
(`5d45541`).

### Phase 1 — screen (`core/corpus_screen.py`) — DONE, iterating on evidence

Commit chain: `dc6d2c1` → `5d45541` → `d591a7d` → `3400e4d` → `fe0973f` →
`18499c5` → `d37ca8f` → `339b96e` → `b8d1f99`.

Key fixes, each with a root cause:

- **Dash-dot axes exported as separate thin collinear segments** carry no dash
  attribute; the dashed-line axis detector found 0.000 everywhere. `_chain_axis`
  detects ≥4 collinear pieces in one y band, gap ≤ 8 mm, coverage ≥ 0.45,
  absolute span ≥ 120 mm (`339b96e`; was 45 %-of-page which is wrong for A2/A3).
  Band-quantized axis leaked into the 1 mm mirror tolerance — `_chain_axis` now
  returns the winning run's exact mean y (`339b96e`).
- **jcrzd decode**: `HoughLinesP` returns `(N, 1, 4)`; iterating raw rows crashed
  with `'numpy.int32' object is not iterable` — fixed + per-file isolation so one
  bad file is UNREADABLE, never a batch failure (`3400e4d`, `18499c5`).
- **Vector mirror symmetry read 0.000** on auto-traced revolution drawings
  (outline paths/fillet arcs) — **raster-mirror symmetry** (`_symmetry_raster`,
  b8d1f99) renders at 150 dpi, compares dark-pixel counts of mirrored row pairs;
  two regimes (both-halves-inked ratio, one-sided coverage); falls back to the
  vector score. Goldens still 30/30 BODY_OF_REVOLUTION (raster sym 0.62–0.74).
- Golden 30/30 forever after `5d45541` exclusion; 39 screen/axis tests pass locally.

### Phase 2 — pipeline on screened candidates — DONE (1 candidate, honest result)

`core/corpus_run.py` runs the full pipeline per candidate with `--no-resume` on
push runs, `error_signature` clustering, Tier-A gt matching (gt_3d matched by stem).

### Phase 3 — benchmark docs — DONE (auto-generated, regenerated by CI)

`core/corpus_report.py` regenerates `docs/CORPUS_BENCHMARK.md` +
`docs/BUG_HARVEST.md` each nightly; committed copies are placeholders until a run
encounters real data. Visual corpus check (`docs/CORPUS_VISUAL_CHECK.md`) — real
corpus section NOT DONE (blocked on download; see file).

### Phases 5–7 — accuracy verdicts / bug harvest triage / nightly hardening — NOT STARTED

Blocked on ≥1 genuine BODY_OF_REVOLUTION page reaching OK end-to-end. Evaluation
so far: **0 pages**. Order of work: (1) verify raster-symmetry effect on the
funnel; (2) root-cause the constant axis ≈ 0.700 and views = 4 telemetry (below);
(3) page_033 NO_DIMS post-mortem; (4) only then harvest pipeline bugs from real
rows.

## 3a. Pipeline post-mortem #1 — page_001 / archive-PDF (2026-11-27, run `45989635683`, commit `b713040`)

Fresh download (cache restore worked; zenodo + jcrzd instant), re-screen +
pipeline re-measured. New funnel: **81 screened → 2 BODY_OF_REVOLUTION**
(archive PDF + page_001 — same first page; see §4), 78 NOT_SUPPORTED,
1 NO_DIMENSIONS, 0 pipeline OK.

- **`page_001` and the archive PDF both processed → `NO_DIMS`, 47 dims parsed
  (40 confident / 7 uncertain, auto_link_rate 0.85, 1 contradiction error),
  `error_signature = "no revolution profile reconstructed"`, wall ~1.6–1.9 s.**
  The dimension stage works on real pages; the *profile* stage returned empty —
  because `find_axis` only considered dash-dot `AXIS` strokes, and on traced
  pages the centre line is exported as separate thin strokes with no dash
  attribute (same root cause as the screen bug, one level deeper).
- **Fix (this push):** shared `detect_axis_chain` in `core/geometry.py` (moved
  verbatim from the screen) + chain fallback in `find_axis`; regression test
  `test_pipeline_axis_chain_fallback_reconstructs_profile`. Local: 141 passed
  (Qt-GUI tests excluded — needs system libxkbcommon).
- **Screen telemetry of the candidates is legit**: archive/page_001 both
  BODY_OF_REVOLUTION at 0.06–0.14 s. page_033 flipped back to NOT_SUPPORTED.
- **PDF census confirms auto-trace micro-segments**: pages 003/005/011/012/014
  carry 3.8k–99.6k line items with p50 segment length 0.02–0.13 mm; the sheets
  were emitted by a trace of a raster, not by CAD export. Clean pages
  (page_001: 403×1.44 pt, 246×0.72 pt, 741 curves) exist but the trace noise
  dominates the corpus.
- **`views = 4` root-caused** (CORPUS-ZENODO-DIAG, run 2026-11-27): every page
  carries exactly one dominant cluster = the GOST **sheet frame**
  (A3: `400x287@(15,5)`; A2: `574x410@(2,9)`); the views gate counted it as a
  view. Fixed: frame-sized clusters (≥80 % of both page dims) are excluded
  from view counting and from `views_detail`.
- **`axis = 0.700` root-caused** (same annotation): the "axis" is a constant
  **stamp-rule / title-block chain at ~95 % of the page height** (A3:
  y ≈ 282.4 mm; A2: y ≈ 405.7 mm) with an identical span of 175.0 mm on every
  sheet — a sheet element, not a revolution axis. A valid revolution axis
  spans the *view* (page_001: y=217.7, span=236.8; page_033: y=135.2,
  span=233.3). Fixed: chains below the GOST title-block zone (y > 0.85 of the
  page height) are rejected as axis evidence (both screen and pipeline
  fallback paths).
- **Curve-arc coverage bug root-caused and fixed**: GOST fillets arrive as
  Bezier curves; v1 ignored curves, so the outline had uncovered gaps and
  `build_half_profile` returned `[]` → pipeline NO_DIMS despite 47 parsed
  dims. Curves are now de Casteljau-flattened to ≤0.1 mm chords
  (`test_fillet_arc_outline_reconstructs_profile`).
- **Multi-page PDFs are now excluded from screening** (the zenodo archive PDF
  screens page 1 only, duplicating page_001); regression tests added.

## 3b. Post-mortem #2 — annotation cap, archive double-processing, 'qu' crash (run `45991993567`, commit `7ac6c76`; and run `45994637154`, commit `cabaffc`)

**b713040 → 7ac6c76 (screen telemetry):**
- Raster symmetry resurrected candidates: **page_001 (v=1, sym=0.72),
  page_010 (v=2, sym=0.71), page_033 (sym=0.50 — below the 0.55 gate),
  page_039 (v=2→1 after frame fix, sym=0.60, ax=0.74)**. Furniture pages
  (axis≡0.700 @ y≈282.4) dropped to axis=0.000 — those verdicts are now
  honest absences, not suppressed evidence.
- **Frame exclusion verified**: every page's dominant cluster is gone
  (page_001 views 2→1; page_034 4 (others); page_039 3→2).
- **Bottom-strip guard verified**: no more axis=0.700 anywhere; genuine axes
  remain (page_001 y=217.7 span=236.8; page_033 y=135.2 span=233.3; page_010
  y=86.8 span=195.2).

**cabaffc run:**
- Screen: **80 screened → 3 BODY_OF_REVOLUTION** (page_001, page_010,
  page_039), 1 NO_DIMENSIONS, jcrzd 40× NOT_SUPPORTED. Pipeline selected **4**
  files — the archive PDF crept back in: `_find_corpus_files` defaults
  unscreened ids to BODY_OF_REVOLUTION (fail-open) and did not skip
  multi-page containers. **Fixed in the next push: `_find_corpus_files` now
  skips multi-page PDFs (same rule as the screen).**
- **All 4 candidates CRASHed: `IndexError: tuple index out of range`,
  dims=0/0.** Root cause: fitz `qu` items are **Quads** (ul/ur/ll/lr corners),
  not quadratic Beziers — my `_quad_chords(item[1..3])` indexed non-existent
  control points. `c` items are 5-tuples and were handled correctly. Fixed:
  `qu` → closed 4-edge shape (like `re`); `_quad_chords` removed; regression
  test `test_quad_item_parsed_as_closed_shape`. Local: 145 passed.

## 4. Measured funnel (commit `339b96e`, check-run `140445276543`, 2026-11-26)

| step | count | denominator / note |
|---|---|---|
| manifest records | 82 | zenodo 42 + jcrzd 40 |
| screened | 81 | 82 manifest = 2 zenodo **archive** rows (PDF + STEP zip) + 40 zenodo page rows + 40 jcrzd rows; screening sees only .pdf/.png/.jpg/… → the `.zip` archive has no row ⇒ 81. Resolved by reading `_fetch_zenodo`: archive PDF is split to `pages/` (limit 40) and its manifest row stays alongside the page rows |
| BODY_OF_REVOLUTION | **1** | zenodo `page_033` |
| NO_DIMENSIONS | 1 | zenodo `page_002` |
| NOT_SUPPORTED | 79 | zenodo 39 + jcrzd 40 |
| processed by pipeline | 1 | page_033 |
| pipeline OK | 0 | **page_033 → NO_DIMS (wall 2.2 s)**, 3D not produced |
| Tier A (matched gt_3d STEP) | **0** | no gt match for processed file |
| Volume/bbox error, accuracy | **NOT MEASURED** | denominator: 0 |

`data/corpus/results.jsonl` (artifact `corpus-results`, 339b96e run): 1 line,
464 B. Screen wall time 0.03–131 s/file (page_029 slowest).

Zenodo per-file evidence sample (same run; axis/sym/views/Ø/dim-tokens as of
339b96e — `sym` all pre-`b8d1f99` vector scores): `page_001` axis=0.95 sym=0.28
views=2 Ø=5; `page_010` axis=0.78 sym=0.84 views=3 Ø=2; `page_011` axis=0.59
sym=0.33; `page_012` axis=0.76 sym=0.14; `page_021` axis=0.52; remaining pages
axis=0.700 (span ≈ 175 mm in every case), sym 0.000–0.02, views=4, Ø 0–13,
dim tokens 27–101.

### Open anomalies (diagnostics added in b8d1f99)

1. **`axis = 0.700` on ~24 zenodo pages** — score saturates at span ≈ 175 mm
   (`CHAIN_SCORE_FULL_MM=250`). Identical span on dozens of independent pages
   means either a shared sheet element (frame/title-block edge, projection
   symbol) or a systematic chain artifact. `axis_y_mm`/`axis_span_mm` per page
   are now emitted; root cause pending the next CI run.
2. **`views = 4` on ~most zenodo pages** — the `_views_count` cap (4) likely
   merges the drawing frame/title-block into two masses on top of the views.
   `views_detail` now lists the counted clusters for every page.
3. **page_033** (the single BODY_OF_REVOLUTION candidate at screening) reached
   the pipeline and returned `NO_DIMS` in 2.2 s — i.e. gates passed screen but
   the dimension stage found nothing (token format? Ø-glyph variants? gost-dim
   parse gap?). Post-mortem pending its (now untruncated) evidence row.
4. **82 vs 81 rows — root-caused** (local reading of `_fetch_zenodo` + evidence):
   the STEP `.zip` archive row never yields a screened file, and the archive-PDF
   manifest row screens as `1- 100 2D orthographic drawings` — **byte-identical
   first page** to `page_001` (axis=0.947, sym=0.284, views=2, Ø=5, tokens=43 on
   both rows). No file is missing; the two archive rows are the source of the
   off-by-one.

## 5. Legal / attribution

- zenodo 24167336 — CC BY 4.0, attribution in README + DATA_SOURCES. Per-file
  rows may be published.
- jcrzd — no license metadata: aggregates only, never per-file publication,
  never committed (corpus downloads are `.gitignore`d).
- ecado — not evaluated in this run.
- MechAtlas — gated; never used.

## 6. Commit / CI index

`dc6d2c1` stem-join gt_3d · `5d45541` golden exclusion · `d591a7d` chain detector
v1 + jcrzd fetch fixes · `3400e4d` per-file isolation · `fe0973f` PDF/JCRZD
diagnostics annotations · `18499c5` run-based chain + HoughLinesP fix ·
`d37ca8f` focused forensics (pages 003/011/014/022; band census 0.75/2.0/4.0 mm) ·
`339b96e` absolute-span chain (≥120 mm), 3 mm bands, exact-mean-y axis;
ci: tests 45981222258 ✓, corpus 45981210124 ✓, build-exe 45981222246 ✓ ·
`b8d1f99` raster-mirror symmetry + chunked annotations + diagnostics.

## 7. Rules learned (carry forward)

- Band-quantize nothing that feeds a tolerance-based comparison.
- Absolute spans, not page-relative fractions, for axis-length evidence.
- Evidence lines must survive CI annotation limits — chunk at ~3.4 KB.
- A screen pass means nothing until the pipeline confirms parseable dimensions;
  report the stage that dropped the file.
- Never widen gates to make a number look better; diagnose, then fix generally.
- `git clean` in the repo root wipes untracked work — snapshot first, always
  (lost this log once already).
