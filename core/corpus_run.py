"""Run the pipeline on every screened BODY_OF_REVOLUTION file (Part 4).

Each file is processed in a **subprocess worker** so one crashing/hanging
file can never abort the batch. The orchestrator enforces a per-file
timeout, appends one JSON line per file to ``data/corpus/results.jsonl``
and is restartable via ``--resume``.

Ground truth (Tier A, real 3D): when a file's manifest record carries
``gt_3d`` (a matched STEP file), the built solid is compared against the
real STEP — volume error %, bbox error % and a mesh-projection silhouette
IoU (best of 24 axis-aligned orientations, 200x64 bins, deflection 0.8 mm).
Unmatched files get ``gt: null`` explicitly.

Usage:
    python -m core.corpus_run --screening data/corpus/screening.csv \
        --manifest data/corpus/manifest.jsonl --out data/corpus/results.jsonl
    # worker mode (used internally):
    python -m core.corpus_run --one <file> --out <tmp.json> [--gt-step <step>]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]

STATUS_OK = "OK"
STATUS_NO_DIMS = "NO_DIMS"
STATUS_CONTRADICTION = "CONTRADICTION"
STATUS_BUILD_FAIL = "BUILD_FAIL"
STATUS_CRASH = "CRASH"
STATUS_TIMEOUT = "TIMEOUT"

_MM_PER_PT = 25.4 / 72.0


# --------------------------------------------------------------------------- #
# error signatures                                                             #
# --------------------------------------------------------------------------- #
def normalize_error_signature(exc_type: str, message: str) -> str:
    msg = re.sub(r"\d+(\.\d+)?", "#", message or "")
    msg = re.sub(r"[A-Za-z]:\\[^\s]*|/[^\s]*", "<path>", msg)
    msg = re.sub(r"\s+", " ", msg).strip()
    return f"{exc_type}: {msg[:140]}"


def _signature_from_traceback(text: str) -> str:
    lines = [l for l in (text or "").splitlines() if l.strip()]
    for line in reversed(lines):
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Failure))\b:?\s*(.*)$", line.strip())
        if m:
            return normalize_error_signature(m.group(1).split(".")[-1], m.group(2))
    tail = lines[-1].strip() if lines else "unknown error"
    return normalize_error_signature("Crash", tail)


# --------------------------------------------------------------------------- #
# ground truth helpers (worker only)                                           #
# --------------------------------------------------------------------------- #
def _silhouette_mask(solid, bounds, bins_x: int = 200, bins_r: int = 64):
    """Binary upper-silhouette mask in the (x, r) revolution plane.

    r = sqrt(y^2 + z^2) measured from the x axis. ``bounds`` = (x0, x1, r_max)
    is shared by both solids being compared, so IoU is positional, not
    scale-normalized. Filled columns = material up to the highest sampled
    point in that x bin (vertices are dense on a tessellated solid).
    """
    import math

    import numpy as np

    x0, x1, r_max = bounds
    grid = np.zeros((bins_r, bins_x), dtype=bool)
    if x1 - x0 <= 1e-9 or r_max <= 1e-9:
        return grid
    verts, _ = solid.tessellate(1.5)
    for v in verts:
        ix = min(bins_x - 1, max(0, int((v.x - x0) / (x1 - x0) * bins_x)))
        iy = min(bins_r - 1, max(0, int(math.hypot(v.y, v.z) / r_max * (bins_r - 1))))
        grid[: iy + 1, ix] = True
    return grid


def _proper_rotations_24():
    """The 24 proper signed permutation matrices (orientation group of the cube)."""
    import itertools

    mats = []
    for perm in itertools.permutations(range(3)):
        base = [[0, 0, 0] for _ in range(3)]
        for i, p in enumerate(perm):
            base[i][p] = 1
        for signs in itertools.product((1, -1), repeat=3):
            m = [[base[i][j] * signs[j] for j in range(3)] for i in range(3)]
            det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                   - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                   + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
            if det == 1:
                mats.append(m)
    assert len(mats) == 24
    return mats


_ROT_24 = _proper_rotations_24()


def _translate_x_to_zero(solid):
    bb = solid.BoundingBox()
    return solid.translate((-bb.xmin, 0.0, 0.0))


def _orientation_best_iou(built, ref) -> float:
    """Silhouette IoU between built solid and reference solid.

    The reference STEP may be oriented arbitrarily, so all 24 axis-aligned
    proper orientations are tried; the best IoU is reported. Both solids are
    translated so their bbox starts at x=0; bins are shared (x over the
    longer of the two lengths, r over the larger radius) — IoU is absolute.
    """
    import cadquery as cq
    import numpy as np

    built = _translate_x_to_zero(built)
    bb = built.BoundingBox()
    built_len = bb.xmax - bb.xmin
    built_r = max(bb.ymax - bb.ymin, bb.zmax - bb.zmin) / 2.0
    built_mask_cache: dict[tuple, object] = {}

    best = 0.0
    for m in _ROT_24:
        # columns of m: images of local x, z axes under the rotation
        try:
            plane = cq.Plane(origin=(0, 0, 0), xDir=(m[0][0], m[1][0], m[2][0]),
                             normal=(m[0][2], m[1][2], m[2][2]))
            loc = cq.Location(plane)
        except Exception:
            continue
        try:
            moved = _translate_x_to_zero(ref.moved(loc))
        except Exception:
            continue
        bb = moved.BoundingBox()
        ref_len = bb.xmax - bb.xmin
        ref_r = max(bb.ymax - bb.ymin, bb.zmax - bb.zmin) / 2.0
        bounds = (0.0, max(built_len, ref_len), max(built_r, ref_r))
        try:
            ref_mask = _silhouette_mask(moved, bounds)
        except Exception:
            continue
        if bounds not in built_mask_cache:
            built_mask_cache[bounds] = _silhouette_mask(built, bounds)
        built_mask = built_mask_cache[bounds]
        union = np.logical_or(built_mask, ref_mask).sum()
        if union:
            inter = np.logical_and(built_mask, ref_mask).sum()
            best = max(best, inter / union)
    return best


def _load_step(path: Path):
    import cadquery as cq

    result = cq.importers.importStep(str(path))
    solids = result.solids().vals()
    if not solids:
        raise ValueError("no solids in STEP file")
    if len(solids) == 1:
        return solids[0]
    return solids[0].fuse(*solids[1:])


def _solid_stats(solid) -> dict:
    bbox = solid.BoundingBox()
    return {
        "volume_mm3": float(solid.Volume()),
        "bbox_mm": {
            "length": float(bbox.xmax - bbox.xmin),
            "diameter": float(max(bbox.ymax - bbox.ymin, bbox.zmax - bbox.zmin)),
        },
        "faces": len(solid.Faces()),
    }


def _compare_with_gt(built_shape, step_path: Path) -> dict:
    ref = _load_step(step_path)
    gt = _solid_stats(ref)
    bb = built_shape.BoundingBox()
    length = bb.xmax - bb.xmin
    diameter = max(bb.ymax - bb.ymin, bb.zmax - bb.zmin)
    vol = float(built_shape.Volume())
    gt_vol, gt_len, gt_dia = gt["volume_mm3"], gt["bbox_mm"]["length"], gt["bbox_mm"]["diameter"]
    return {
        "volume_mm3": round(gt_vol, 1),
        "bbox_mm": {k: round(v, 3) for k, v in gt["bbox_mm"].items()},
        "faces": gt["faces"],
        "volume_error_pct": abs(vol - gt_vol) / gt_vol * 100.0 if gt_vol else None,
        "bbox_length_error_pct": abs(length - gt_len) / gt_len * 100.0 if gt_len else None,
        "bbox_diameter_error_pct": abs(diameter - gt_dia) / gt_dia * 100.0 if gt_dia else None,
        "silhouette_iou": float(_orientation_best_iou(built_shape, ref)),
    }


# --------------------------------------------------------------------------- #
# worker                                                                       #
# --------------------------------------------------------------------------- #
def _process_file(path: Path, gt_step: Path | None) -> dict:
    """Full pipeline for one drawing; never raises."""
    record = {
        "id": path.stem,
        "source": "",
        "verdict": "",
        "dims_total": 0,
        "dims_confident": 0,
        "dims_uncertain": 0,
        "auto_link_rate": None,
        "contradictions": 0,
        "contradiction_errors": 0,
        "parsing_time_s": None,
        "build_time_s": None,
        "volume_mm3": None,
        "bbox_mm": None,
        "status": STATUS_OK,
        "error_signature": None,
        "gt": None,
    }

    t0 = time.perf_counter()
    try:
        from core.cad_builder import build_solid
        from core.constraint_solver import (
            estimate_scale,
            scan_diameter_tol_mm,
            scan_linear_tol_mm,
            solve_constraints,
        )
        from core.ocr_gost import recognize_dimensions
        from core.pdf_parser import parse_pdf
        from core.scan_pipeline import _DEFAULT_DPI, parse_scan, read_dpi

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            linear_tol = diameter_tol = None
            drawing = parse_pdf(path)
            ocr_note = None
        else:
            dpi = read_dpi(path) or _DEFAULT_DPI
            linear_tol, diameter_tol = scan_linear_tol_mm(dpi), scan_diameter_tol_mm(dpi)
            try:
                drawing = parse_scan(path, dpi=dpi, ocr=True)
                ocr_note = None
            except RuntimeError as exc:
                # no local OCR engine — degrade honestly: geometry only, no dims
                drawing = parse_scan(path, dpi=dpi, ocr=False)
                ocr_note = f"ocr_unavailable: {exc}"

        dimensions = recognize_dimensions(drawing)
        scaled, contradictions = solve_constraints(
            dimensions, drawing.profile,
            bore_diameter=drawing.bore_diameter,
            linear_tol_mm=linear_tol,
            diameter_tol_mm=diameter_tol,
        )
        parse_s = time.perf_counter() - t0
        if ocr_note:
            record["notes"] = [ocr_note]
        record["parsing_time_s"] = round(parse_s, 3)
        record["dims_total"] = len(dimensions)
        record["dims_confident"] = sum(1 for d in dimensions if not d.is_uncertain)
        record["dims_uncertain"] = record["dims_total"] - record["dims_confident"]
        record["auto_link_rate"] = (record["dims_confident"] / record["dims_total"]) if record["dims_total"] else None
        record["contradictions"] = len(contradictions)
        record["contradiction_errors"] = sum(1 for c in contradictions if c.severity == "error")

        if not drawing.profile:
            record["status"] = STATUS_NO_DIMS
            # CI telemetry: why the outline walk failed (axis, line counts,
            # missing-coverage interval) instead of an opaque label
            try:
                from core.geometry import profile_debug

                dbg = profile_debug()
                if dbg:
                    record["profile_debug"] = dbg
            except Exception:
                pass
            try:
                from core.pdf_parser import pdf_stats

                stats = pdf_stats()
                if stats:
                    record["pdf_stats"] = stats
            except Exception:
                pass
            record["error_signature"] = "no revolution profile reconstructed"
            return record
        if record["contradiction_errors"]:
            record["status"] = STATUS_CONTRADICTION
            return record

        scale = estimate_scale(dimensions, drawing.profile, linear_tol_mm=linear_tol)
        bore_true = drawing.bore_diameter * scale if drawing.bore_diameter else None
        record["scale"] = scale
        record["bore_diameter_true_mm"] = bore_true
        record["proposed_by_geometry"] = sum(1 for d in dimensions if getattr(d, "proposed_by_geometry", False))
        build_t0 = time.perf_counter()
        try:
            solid = build_solid(scaled, dimensions, bore_diameter=bore_true)
        except BaseException as exc:
            record["status"] = STATUS_BUILD_FAIL
            record["error_signature"] = normalize_error_signature(type(exc).__name__, str(exc))
            record["build_time_s"] = round(time.perf_counter() - build_t0, 3)
            return record
        record["build_time_s"] = round(time.perf_counter() - build_t0, 3)
        stats = _solid_stats(solid.val())
        record["volume_mm3"] = round(stats["volume_mm3"], 1)
        record["bbox_mm"] = {k: round(v, 3) for k, v in stats["bbox_mm"].items()}
        record["status"] = STATUS_OK if record["dims_total"] else STATUS_NO_DIMS

        if gt_step:
            try:
                record["gt"] = _compare_with_gt(solid.val(), Path(gt_step))
            except BaseException as exc:
                record["gt"] = None
                record["gt_error"] = normalize_error_signature(type(exc).__name__, str(exc))
        return record

    except BaseException as exc:  # pipeline crash must never propagate
        import traceback

        record["status"] = STATUS_CRASH
        record["error_signature"] = _signature_from_traceback(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        record["parsing_time_s"] = round(time.perf_counter() - t0, 3)
        return record


def _worker_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gt-step", default=None)
    args = ap.parse_args(argv)
    result = _process_file(Path(args.one), Path(args.gt_step) if args.gt_step else None)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- #
# orchestrator                                                                 #
# --------------------------------------------------------------------------- #
def _load_screening(path: Path) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            verdicts[row["id"]] = row["verdict"]
    return verdicts


def _load_manifest(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            records[rec["id"]] = rec
    return records


def _find_corpus_files(corpus: Path) -> dict[str, Path]:
    exts = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    out = {}
    for p in corpus.rglob("*"):
        if not (p.suffix.lower() in exts and p.is_file()):
            continue
        if "/golden/" in p.as_posix():
            continue
        # multi-page PDFs are containers (the zenodo archive PDF screens page 1
        # only); the split `pages/` are the real corpus units
        if p.suffix.lower() == ".pdf":
            try:
                import fitz
                with fitz.open(p) as doc:
                    if doc.page_count > 1:
                        continue
            except Exception:
                pass
        out[p.stem] = p
    return out


def _run_worker(file: Path, gt_step: Path | None, timeout: float, workdir: Path) -> tuple[dict | None, str]:
    tmp = workdir / f".corpus_result_{os.getpid()}_{abs(hash(str(file)))}.json"
    cmd = [sys.executable, "-m", "core.corpus_run", "--one", str(file), "--out", str(tmp)]
    if gt_step:
        cmd += ["--gt-step", str(gt_step)]

    preexec = None
    if os.name == "posix":
        def _limits():
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
        preexec = _limits

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              preexec_fn=preexec, check=False)
    except subprocess.TimeoutExpired:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None, "timeout"
    if not tmp.exists():
        sig = _signature_from_traceback((proc.stderr or b"").decode("utf-8", "replace"))
        return None, sig or "crashed before writing a result"
    try:
        record = json.loads(tmp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        record = None
    try:
        tmp.unlink()
    except OSError:
        pass
    return record, ""


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--one" in argv:
        return _worker_main(argv)

    ap = argparse.ArgumentParser(description="Run the pipeline on the screened corpus (subprocess-isolated).")
    ap.add_argument("--corpus", default=str(REPO_ROOT / "data" / "corpus"))
    ap.add_argument("--screening", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--include-verdicts", default="BODY_OF_REVOLUTION",
                    help="comma-separated verdicts to process (default: BODY_OF_REVOLUTION)")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus)
    screening_path = Path(args.screening) if args.screening else corpus / "screening.csv"
    manifest_path = Path(args.manifest) if args.manifest else corpus / "manifest.jsonl"
    results_path = Path(args.out) if args.out else corpus / "results.jsonl"

    verdicts = _load_screening(screening_path) if screening_path.exists() else {}
    files = _find_corpus_files(corpus)
    files = {fid: p for fid, p in files.items() if p.is_file()}
    wanted = {v.strip() for v in args.include_verdicts.split(",") if v.strip()}

    selected = {
        fid: p for fid, p in files.items()
        if verdicts.get(fid, "BODY_OF_REVOLUTION") in wanted
    }

    done_ids: set[str] = set()
    if args.resume and results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done_ids.add(json.loads(line).get("id", ""))
    selected = {fid: p for fid, p in selected.items() if fid not in done_ids}
    if args.limit is not None:
        selected = dict(list(sorted(selected.items()))[: args.limit])

    manifest = _load_manifest(manifest_path)
    # manifest ids are namespaced (e.g. "zenodo-page-page_001") while pipeline
    # ids are file stems ("page_001") — join on the path stem as well or the
    # gt_3d match can never fire
    manifest_by_stem: dict[str, dict] = {}
    for _mid, _rec in manifest.items():
        _p = _rec.get("path") or ""
        if _p:
            manifest_by_stem.setdefault(Path(_p).stem, _rec)
    step_files = list(corpus.rglob("*.step")) + list(corpus.rglob("*.stp"))

    print(f"corpus: {len(files)} file(s); selected {len(selected)} for verdicts {sorted(wanted)}"
          + (f"; resumed past {len(done_ids)} already done" if done_ids else ""))
    if not selected:
        print("nothing to run")
        return 0

    import datetime
    with open(results_path, "a", encoding="utf-8") as out:
        for i, (fid, path) in enumerate(sorted(selected.items()), 1):
            rec = manifest.get(fid) or manifest_by_stem.get(fid, {})
            gt_name = rec.get("gt_3d")
            gt_step = next((p for p in step_files if p.name == gt_name), None) if gt_name else None
            t0 = time.perf_counter()
            record, err = _run_worker(path, gt_step, args.timeout, corpus)
            elapsed = time.perf_counter() - t0
            if record is None:
                record = {
                    "id": fid,
                    "source": rec.get("source", ""),
                    "verdict": verdicts.get(fid, ""),
                    "dims_total": 0, "dims_confident": 0, "dims_uncertain": 0,
                    "auto_link_rate": None, "contradictions": 0,
                    "parsing_time_s": None, "build_time_s": None,
                    "volume_mm3": None, "bbox_mm": None,
                    "status": STATUS_TIMEOUT if err == "timeout" else STATUS_CRASH,
                    "error_signature": err if err != "timeout" else "worker timeout (wall clock)",
                    "gt": None,
                }
            record["id"] = fid
            record["source"] = rec.get("source", "")
            record["verdict"] = verdicts.get(fid, "")
            record["gt_3d"] = gt_name
            record["wall_time_s"] = round(elapsed, 3)
            record["recorded_at"] = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(selected):
                print(f"[{i}/{len(selected)}] {fid}: {record['status']} ({elapsed:.1f}s)")
    print(f"wrote {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
