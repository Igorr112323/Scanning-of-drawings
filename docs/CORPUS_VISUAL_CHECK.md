# Visual check — corpus verdicts vs human eyes (Part 9)

> **Honesty banner.** The real corpus has NOT been downloaded yet (corpus hosts are
> unreachable from the build sandbox; the nightly workflow `.github/workflows/corpus-nightly.yml`
> is the only automated path). Everything below is validated on the committed **synthetic**
> golden fixtures (`data/corpus/golden/`, `provenance: synthetic-generated`). Real-drawing
> visual verification is **NOT DONE** and is listed as such — it must happen after the first
> nightly/owner-machine download, on at least 10 randomly sampled corpus files.

## Method

1. Synthetic goldens rendered at 110 DPI (PyMuPDF) and inspected by eye by the agent (2026-11-26).
2. Screening verdict obtained from `core/corpus_screen.py` for each file.
3. Five built solids exported to STEP and re-measured (volume vs analytic GT, bbox).

## Results — synthetic goldens (10 inspected)

| id | screening verdict | visual content | agree? |
|---|---|---|---|
| golden_001 | BODY_OF_REVOLUTION | half-profile, stepped shaft, Ø33/Ø12/Ø39, axis dash-dot, length 95 | yes |
| golden_002 | BODY_OF_REVOLUTION | stepped shaft Ø42/Ø21/Ø42, axis, length 95 | yes |
| golden_003 | BODY_OF_REVOLUTION | stepped shaft Ø27/Ø21/Ø36, axis, length 110 | yes |
| golden_004 | BODY_OF_REVOLUTION | stepped shaft Ø30/Ø30/Ø27/Ø27, axis, length 120 | yes |
| golden_005 | BODY_OF_REVOLUTION | 4-step shaft Ø21/Ø15/Ø27/Ø39, axis, length 135 | yes |
| golden_006 | BODY_OF_REVOLUTION | Ø12→Ø30→Ø24 rising profile, axis, length 80 | yes |
| golden_007 | BODY_OF_REVOLUTION | plain Ø18 cylinder profile, axis, length 95 | yes |
| golden_008 | BODY_OF_REVOLUTION | 5-step shaft Ø33/Ø39/Ø27/Ø30/Ø39, axis, length 165 | yes |
| golden_009 | BODY_OF_REVOLUTION | Ø36/Ø12/Ø33/Ø18 profile, axis, length 145 | yes |
| golden_010 | BODY_OF_REVOLUTION | Ø21/Ø36/Ø36/Ø15 profile, axis, length 155 | yes |

Built solids exported and re-measured (headless, no viewer available):

| id | STEP volume [cm³] | analytic GT [cm³] | bbox | GT bbox | Δvol |
|---|---|---|---|---|---|
| golden_001 | 76.59 | 76.59 | 95.0×39.0 mm | 95.0×39.0 | <0.001% |
| golden_004 | 76.76 | 76.76 | 120.0×30.0 mm | 120.0×30.0 | <0.001% |
| golden_007 | 24.17 | 24.17 | 95.0×18.0 mm | 95.0×18.0 | <0.001% |
| golden_008 | 152.01 | 152.01 | 165.0×39.0 mm | 165.0×39.0 | <0.001% |
| golden_010 | 96.42 | 96.42 | 155.0×36.0 mm | 155.0×36.0 | <0.001% |

## Real corpus (NOT DONE — blocked on downloads)

| requirement | status |
|---|---|
| ≥10 real downloaded drawings eyeballed vs screening verdict | NOT DONE |
| 5 built solids from real drawings inspected | NOT DONE |
| suspiciously good metrics investigated (e.g. 100% OK on real data) | NOT DONE — no real run yet |

Owner/CI action: after the first nightly run, download the `corpus-results` artifact,
sample ≥10 files from `results.jsonl`, render them, and fill this table with:

```
id | screening verdict | visual content | agree? |
```
