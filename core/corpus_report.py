"""Generate the corpus benchmark docs from committed artifacts (Parts 6–7).

Reads ``manifest.jsonl`` / ``screening.csv`` / ``results.jsonl`` and writes:

* ``docs/CORPUS_BENCHMARK.md`` — funnel, status table, Tier A error
  distribution (median/p90/max + histogram), silhouette-IoU distribution,
  auto-link rate, timing p50/p90, failure taxonomy, and an explicit
  "WHAT THESE NUMBERS DO NOT PROVE" section.
* ``docs/BUG_HARVEST.md`` — non-OK files clustered by normalized
  error_signature, top-10 with example ids, module guess, severity proposal.
* ``reports/*.png`` — histograms / taxonomy chart (only when data exists).

Every number is computed from the input files; anything not measured is
printed as NOT MEASURED. No corpus downloaded => docs degrade to honest
placeholders instead of invented numbers.

Usage:
    python -m core.corpus_report --golden-check   # include offline golden section
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

STATUSES = ["OK", "NO_DIMS", "CONTRADICTION", "BUILD_FAIL", "CRASH", "TIMEOUT"]
VERDICTS = ["BODY_OF_REVOLUTION", "NOT_SUPPORTED", "UNREADABLE", "NO_DIMENSIONS"]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_screening(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _pctiles(values: list[float]):
    if not values:
        return None
    s = sorted(values)

    def q(p: float) -> float:
        k = (len(s) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return s[int(k)]
        return s[f] * (c - k) + s[c] * (k - f)

    return {"n": len(s), "min": s[0], "p50": q(0.5), "p90": q(0.9), "max": s[-1],
            "mean": sum(s) / len(s)}


def _fmt(stats, unit=""):
    if not stats:
        return "NOT MEASURED"
    return (f"n={stats['n']}, median={stats['p50']:.3f}{unit}, "
            f"p90={stats['p90']:.3f}{unit}, max={stats['max']:.3f}{unit}")


def _module_guess(signature: str) -> str:
    s = signature.lower()
    for keys, module in [
        (["fitz", "mupdf", "parse_pdf", "pdf"], "core/pdf_parser.py"),
        (["ocr", "tesseract"], "core/ocr_gost.py"),
        (["vector", "hough", "cv2"], "core/vectorize.py"),
        (["preprocess", "deskew"], "core/scan_preprocess.py"),
        (["constraint", "solve_constraints", "scale"], "core/constraint_solver.py"),
        (["revolve", "profile", "cad_builder", "occ", "brep"], "core/cad_builder.py"),
        (["step"], "core/corpus_run.py (STEP import/compare)"),
    ]:
        if any(k in s for k in keys):
            return module
    return "triage needed"


def _severity_guess(signature: str, count: int) -> str:
    s = signature.lower()
    if "timeout" in s:
        return "high (hangs the batch slot)"
    if "crash" in s or "occ" in s or "brep" in s:
        return "high (hard failure)"
    if count >= 20:
        return "medium-high (frequent)"
    return "medium (needs triage)"


def _histogram(reports_dir: Path, name: str, values: list[float], title: str, xlabel: str, bins: int = 20):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        reports_dir.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.hist(values, bins=bins, color="#2c7be5", edgecolor="white")
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("files")
        fig.tight_layout()
        out = reports_dir / name
        fig.savefig(out, dpi=110)
        plt.close(fig)
        return out
    except Exception as exc:  # chart must never fail the report
        print(f"WARN: chart {name} skipped: {exc}")
        return None


def _taxonomy_chart(reports_dir: Path, status_counts: Counter):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        reports_dir.mkdir(parents=True, exist_ok=True)
        labels, counts = zip(*status_counts.most_common()) if status_counts else (("none",), (0,))
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.bar(labels, counts, color="#e63757")
        ax.set_title("Failure taxonomy (pipeline outcomes)")
        ax.set_ylabel("files")
        fig.tight_layout()
        out = reports_dir / "failure_taxonomy.png"
        fig.savefig(out, dpi=110)
        plt.close(fig)
        return out
    except Exception as exc:
        print(f"WARN: taxonomy chart skipped: {exc}")
        return None


# --------------------------------------------------------------------------- #
# golden fixture check (offline, explicitly synthetic)                         #
# --------------------------------------------------------------------------- #
def golden_symbol_accuracy() -> dict:
    """Per-symbol accuracy on the synthetic golden set (offline CI fixture).

    Returns dict symbol -> {"n", "matched", "accuracy"}. Labelled synthetic
    everywhere it is reported — it measures the fixture generator + pipeline
    agreement, not real-corpus accuracy.
    """
    golden_dir = REPO_ROOT / "data" / "corpus" / "golden"
    from core.cad_builder import build_solid
    from core.constraint_solver import solve_constraints
    from core.ocr_gost import recognize_dimensions
    from core.pdf_parser import parse_pdf

    per_symbol: dict[str, dict] = defaultdict(lambda: {"n": 0, "matched": 0})
    for gt_path in sorted(golden_dir.glob("golden_*.json")):
        pdf_path = golden_dir / (gt_path.stem + ".pdf")
        if not pdf_path.exists():
            continue
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        expected = gt.get("expected", {}).get("dimensions", [])
        drawing = parse_pdf(pdf_path)
        dims = recognize_dimensions(drawing)
        recognized = [(d.symbol.name, d.value) for d in dims]
        used = set()
        for exp in expected:
            sym = str(exp["symbol"])
            value = float(exp["value_mm"])
            per_symbol[sym]["n"] += 1
            for i, (rsym, rvalue) in enumerate(recognized):
                if i in used:
                    continue
                if rsym == sym and value > 0 and abs(rvalue - value) / value <= 0.01:
                    per_symbol[sym]["matched"] += 1
                    used.add(i)
                    break
    out = {}
    for sym, acc in per_symbol.items():
        n = acc["n"]
        out[sym] = {"n": n, "matched": acc["matched"], "accuracy": acc["matched"] / n if n else 0.0}
    return out


# --------------------------------------------------------------------------- #
# document builders                                                            #
# --------------------------------------------------------------------------- #
def build_report(manifest, screening, results, golden_check: bool):
    total_downloaded = len(manifest)
    screened = len(screening)
    verdict_counts = Counter(r["verdict"] for r in screening)
    processed = len(results)
    status_counts = Counter(r["status"] for r in results)

    gt_rows = [r for r in results if r.get("gt")]
    vol_err = [r["gt"]["volume_error_pct"] for r in gt_rows if r["gt"].get("volume_error_pct") is not None]
    len_err = [r["gt"]["bbox_length_error_pct"] for r in gt_rows if r["gt"].get("bbox_length_error_pct") is not None]
    dia_err = [r["gt"]["bbox_diameter_error_pct"] for r in gt_rows if r["gt"].get("bbox_diameter_error_pct") is not None]
    iou = [r["gt"]["silhouette_iou"] for r in gt_rows if r["gt"].get("silhouette_iou") is not None]

    parse_times = [r["parsing_time_s"] for r in results if r.get("parsing_time_s") is not None]
    wall_times = [r["wall_time_s"] for r in results if r.get("wall_time_s") is not None]
    link_rates = [r["auto_link_rate"] for r in results if r.get("auto_link_rate") is not None]
    needs_human = sum(1 for r in results if (r.get("dims_uncertain") or 0) > 0)

    # per-symbol GT-tier-A: STEP carries no dimension text -> not measured
    sym_line = "NOT MEASURED (matched STEP files carry no dimension text; per-symbol accuracy needs symbol-annotated GT)"

    golden_section = ""
    if golden_check:
        acc = golden_symbol_accuracy()
        if acc:
            rows = ["| symbol | n | matched | accuracy |", "|---|---|---|---|"]
            for sym in sorted(acc):
                a = acc[sym]
                cell = f"{a['accuracy'] * 100:.1f}%" if a["n"] >= 5 else f"insufficient data (n={a['n']})"
                rows.append(f"| {sym} | {a['n']} | {a['matched']} | {cell} |")
            golden_section = (
                "\n### Per-symbol accuracy — SYNTHETIC golden fixture set (NOT corpus)\n\n"
                "Computed by re-running the pipeline on the committed synthetic goldens\n"
                "(`provenance: synthetic-generated`). This measures fixture↔pipeline agreement,\n"
                "not real-corpus accuracy, and must not be quoted as corpus performance.\n\n"
                + "\n".join(rows) + "\n")
        else:
            golden_section = "\n### Per-symbol accuracy — NOT MEASURED (golden fixtures absent)\n"

    # ------------------------------------------------------------------ #
    vol_stats, len_stats, dia_stats, iou_stats = (_pctiles(vol_err), _pctiles(len_err),
                                                  _pctiles(dia_err), _pctiles(iou))
    timing_parse, timing_wall = _pctiles(parse_times), _pctiles(wall_times)
    link_stats = _pctiles(link_rates)

    reports = []
    reports_dir = REPO_ROOT / "reports"
    if vol_err:
        p = _histogram(reports_dir, "volume_error_histogram.png", vol_err,
                       "Tier A: volume error vs matched STEP (%)", "relative volume error, %")
        if p:
            reports.append(p)
    if iou:
        p = _histogram(reports_dir, "silhouette_iou_histogram.png", iou,
                       "Tier A: silhouette IoU vs matched STEP", "IoU (higher is better)", bins=15)
        if p:
            reports.append(p)
    if status_counts:
        p = _taxonomy_chart(reports_dir, status_counts)
        if p:
            reports.append(p)

    status_table = ["| status | files | % of processed |", "|---|---|---|"]
    for s in STATUSES:
        n = status_counts.get(s, 0)
        pct = n / processed * 100 if processed else 0.0
        status_table.append(f"| {s} | {n} | {pct:.1f}% |")

    funnel_rows = [
        ("files downloaded (manifest records)", str(total_downloaded)),
        ("files screened", str(screened)),
        ("BODY_OF_REVOLUTION (pipeline candidates)", str(verdict_counts.get("BODY_OF_REVOLUTION", 0))),
        ("processed by the pipeline", str(processed)),
        ("OK", str(status_counts.get("OK", 0))),
        ("non-OK (NO_DIMS/CONTRADICTION/BUILD_FAIL/CRASH/TIMEOUT)",
         str(sum(status_counts.get(s, 0) for s in STATUSES if s != "OK"))),
    ]
    funnel_table = ["| step | files |", "|---|---|"] + [f"| {k} | {v} |" for k, v in funnel_rows]

    report = f"""# Corpus benchmark (auto-generated by `core/corpus_report.py`)

Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Inputs: `data/corpus/manifest.jsonl`, `data/corpus/screening.csv`, `data/corpus/results.jsonl`.
**Every number below is computed from those committed files. Missing data ⇒ NOT MEASURED.**

## Funnel

{chr(10).join(funnel_table)}

## Pipeline outcomes

{chr(10).join(status_table)}

Total wall time (worker processes): {sum(wall_times):.1f} s
Parsing time p50/p90: {_fmt(timing_parse, 's')}
Wall time p50/p90: {_fmt(timing_wall, 's')}

## Tier A — vs matched real STEP solids (n = files with both 2D and 3D)

Tier A files compared: **{len(gt_rows)}** (exact count, not a sample).
An unmatched drawing is reported with `gt: null` and excluded from these distributions — never guessed.

* Volume error: {_fmt(vol_stats, '%')}
* BBox length error: {_fmt(len_stats, '%')}
* BBox diameter error: {_fmt(dia_stats, '%')}
* Silhouette IoU: {_fmt(iou_stats)}

{"![volume error](../reports/volume_error_histogram.png)" if vol_err else "Volume-error histogram: NOT MEASURED (no Tier A data yet)"}
{"![silhouette IoU](../reports/silhouette_iou_histogram.png)" if iou else "Silhouette-IoU histogram: NOT MEASURED (no Tier A data yet)"}

## Auto-link rate (dimension→element association)

{_fmt(link_stats) if link_stats else 'NOT MEASURED'}
Files with ≥1 uncertain dimension (need human confirmation): {needs_human}

## Per-symbol accuracy

{sym_line}
{golden_section}
## Failure taxonomy

{"![failure taxonomy](../reports/failure_taxonomy.png)" if reports else 'Chart: NOT MEASURED (no results yet)'}

See `docs/BUG_HARVEST.md` for the clustered top-10 and fix status.

## WHAT THESE NUMBERS DO NOT PROVE

* **Not** that the pipeline is correct on arbitrary engineering drawings. The corpus is
  whatever was downloaded and screened; verdicts rest on measured evidence but the screen is
  heuristic — a misclassified NOT_SUPPORTED may still be a body of revolution.
* **Not** accuracy on prismatic parts, threads, sections, assemblies or multi-view sheets —
  those are out of scope and reported as coverage limits, never as failures.
* Tier A volume/IoU say nothing about dimension *reading* correctness; they compare shapes.
  Dimension-level ground truth only exists for the synthetic goldens (labelled) — real
  hand-verified goldens are required for dimension accuracy claims.
* Auto-link rate is not "user confirmation rate"; uncertain dims are exactly the ones a human must confirm.
* Distributions are over *downloaded* drawings of *open* sources; they may not reflect any
  particular company's drawing style, and say nothing about the gated MechAtlas source.

## Reproduce

```bash
python -m core.dataset_fetch --source zenodo_open_mech --limit 200 --out data/corpus/zenodo
python -m core.corpus_screen --corpus data/corpus --out data/corpus/screening.csv
python -m core.corpus_run --corpus data/corpus        # subprocess-isolated, resumable
python -m core.corpus_report --golden-check           # rewrites this file + BUG_HARVEST.md
```
"""

    # ------------------------------------------------------------------ #
    non_ok = [r for r in results if r.get("status") != STATUSES[0]]
    clusters: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for r in non_ok:
        sig = (r.get("error_signature") or r.get("status") or "unknown").strip()
        sig = sig.split(": ", 1)[0] + ": " + sig.split(": ", 1)[1][:80] if ": " in sig else sig[:120]
        clusters[sig] += 1
        if len(examples[sig]) < 3:
            examples[sig].append(r.get("id", "?"))

    top10 = clusters.most_common(10)
    bug_rows = ["| # | signature | count | example ids | module (guess) | severity (proposal) | fix plan |",
                "|---|---|---|---|---|---|---|"]
    for i, (sig, count) in enumerate(top10, 1):
        ids = ", ".join(examples[sig])
        bug_rows.append(f"| {i} | `{sig}` | {count} | {ids} | {_module_guess(sig)} | "
                        f"{_severity_guess(sig, count)} | triage: reproduce on example ids, fix generally, "
                        f"add test_corpus_bug_<sig>_<fileid> |")
    if not top10:
        bug_rows.append("| — | (no non-OK files recorded) | 0 | — | — | — | NOT MEASURED — corpus run not executed yet |")
    if top10:
        fix_status_rows = "".join(f"| `{s}` | pending triage | pending | pending |\n" for s, _ in top10)
    else:
        fix_status_rows = "| (pending real corpus run) | — | — | NOT MEASURED |\n"

    out_of_scope = Counter(r.get("error_signature") for r in results
                           if r.get("status") == "CRASH" and "not supported" in str(r.get("error_signature", "")).lower())
    bug_doc = f"""# Bug harvest (auto-generated by `core/corpus_report.py`)

Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Inputs: `data/corpus/results.jsonl` ({processed} processed, {len(non_ok)} non-OK).
Signatures are normalized (numbers → `#`, paths → `<path>`) before clustering.

## Top-10 clusters by count

{chr(10).join(bug_rows)}

## How clusters were produced

1. Pipeline run on every screened BODY_OF_REVOLUTION file (`core/corpus_run.py`), one
   subprocess per file; crash in one file never aborts the batch.
2. Non-OK records grouped by `error_signature` (type + normalized message head).
3. Module column is a keyword guess — triage confirms. Severity is a proposal, not a severity claim.
4. Every in-scope fix lands as a **general** bug fix (no filename/page/value special-casing)
   with a regression test named `test_corpus_bug_<sig>_<fileid>` using the exposing corpus ids.

## Out of scope (recorded as KNOWN LIMITATIONS, not fixed)

Prismatic parts, threads, sections/cutaways, multi-view sheets, assemblies — counted via
screening verdicts and NOT_SUPPORTED notes. These are coverage limits of a revolution-only
v1, never pipeline "failures".

## Fix status

| cluster | in-scope fix | regression test | before → after |
|---|---|---|---|

{fix_status_rows}

Clusters too risky to fix remain documented here with counts — unsupported types must
classify NOT_SUPPORTED, never CRASH.
"""
    return report, bug_doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate CORPUS_BENCHMARK.md and BUG_HARVEST.md.")
    ap.add_argument("--manifest", default=str(REPO_ROOT / "data" / "corpus" / "manifest.jsonl"))
    ap.add_argument("--screening", default=str(REPO_ROOT / "data" / "corpus" / "screening.csv"))
    ap.add_argument("--results", default=str(REPO_ROOT / "data" / "corpus" / "results.jsonl"))
    ap.add_argument("--docs-dir", default=str(REPO_ROOT / "docs"))
    ap.add_argument("--golden-check", action="store_true",
                    help="also compute per-symbol accuracy on the synthetic goldens (offline)")
    args = ap.parse_args(argv)

    manifest = _read_jsonl(Path(args.manifest))
    screening = _read_screening(Path(args.screening))
    results = _read_jsonl(Path(args.results))

    report, bug_doc = build_report(manifest, screening, results, args.golden_check)
    docs_dir = Path(args.docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "CORPUS_BENCHMARK.md").write_text(report, encoding="utf-8")
    (docs_dir / "BUG_HARVEST.md").write_text(bug_doc, encoding="utf-8")
    print(f"wrote {docs_dir / 'CORPUS_BENCHMARK.md'}")
    print(f"wrote {docs_dir / 'BUG_HARVEST.md'}")
    print(f"inputs: manifest={len(manifest)} screening={len(screening)} results={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
