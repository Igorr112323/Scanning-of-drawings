"""Screen downloaded corpus files into supported / unsupported buckets (Part 3).

Evidence-based classification — no filename guessing. Every verdict carries
its evidence so it can be audited:

  BODY_OF_REVOLUTION — a dominant horizontal GOST dash-dot axis line
      (longest dashed horizontal span ≥ 45% of the page width) with contour
      ink on both sides (mirror symmetry ≥ threshold), and at most two view
      clusters.
  NOT_SUPPORTED      — parsed, but no revolution layout (L-brackets, plates,
      multi-view assemblies, …). Counted as a *coverage limit*, not as a
      failure of the pipeline.
  NO_DIMENSIONS      — parsed, but zero dimension-like tokens and zero Ø in
      the text layer (typical for drawing-reading exercise sheets).
  UNREADABLE         — no usable content (empty page, failed decode, sub-
      quality raster). Excluded from every metric.

Usage:
    python -m core.corpus_screen --corpus data/corpus --out data/corpus/screening.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VERDICTS = ("BODY_OF_REVOLUTION", "NOT_SUPPORTED", "UNREADABLE", "NO_DIMENSIONS")

MIN_TEXT_TOKENS = 2
SYMMETRY_MIN = 0.55
AXIS_MIN = 0.6
RASTER_AXIS_MIN = 0.5
MIN_IMAGE_SIDE = 640      # px — quality gate for scans
MIRROR_TOL_MM = 1.0       # mirror-match tolerance between halves
CHAIN_MIN_PIECES = 4      # collinear pieces needed for a dash-dot chain
CHAIN_MAX_GAP_MM = 8.0    # GOST dash-dot gaps are 1.5–3 mm; 8 mm is generous
CHAIN_MIN_COVERAGE = 0.45 # dash-dot cadence is ~70-80% coverage
CHAIN_Y_BAND_MM = 0.75    # segments in the same y band belong to one chain
CHAIN_AXIS_SPAN = 0.45    # chain must span at least this fraction of the page width

_DIM_RE = re.compile(r"^(Ø|⌀|∅|Φ|%%c|R|M)?\s*\d{1,4}([.,]\d{1,4})?(\s*[xхX×].*)?$", re.IGNORECASE)
_DIA_RE = re.compile(r"(Ø|⌀|∅|Φ|%%c)", re.IGNORECASE)

MM_PER_PT = 25.4 / 72.0


@dataclass
class Evidence:
    path: str
    verdict: str
    axis_score: float = 0.0
    symmetry_score: float = 0.0
    dia_count: int = 0
    dim_token_count: int = 0
    views_count: int = 0
    text_layer: bool = False
    reason: str = ""

    def csv_row(self) -> dict:
        return {
            "id": Path(self.path).stem,
            "path": self.path,
            "verdict": self.verdict,
            "axis_score": f"{self.axis_score:.3f}",
            "symmetry_score": f"{self.symmetry_score:.3f}",
            "dia_count": self.dia_count,
            "dim_token_count": self.dim_token_count,
            "views_count": self.views_count,
            "text_layer": int(self.text_layer),
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# shared helpers                                                               #
# --------------------------------------------------------------------------- #
def _dim_token_count(tokens: list[str]) -> int:
    return sum(1 for t in tokens if _DIM_RE.match(t))


def _dia_token_count(tokens: list[str]) -> int:
    return sum(1 for t in tokens if _DIA_RE.search(t))


def _views_count(boxes: list[tuple[float, float, float, float]]) -> int:
    """Rough view-cluster count: union-find over stroke bboxes."""
    if not boxes:
        return 0
    inflate = 6.0  # mm — pieces of one view merge
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # sweep over x — with thousands of stroke boxes (acad pages split dash-dot
    # axes into many segments) the naive O(N^2) blows up to minutes per page
    order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
    sboxes = [boxes[i] for i in order]
    remap = order
    for i in range(len(sboxes)):
        a = sboxes[i]
        for j in range(i + 1, len(sboxes)):
            b = sboxes[j]
            if b[0] > a[2] + inflate:
                break
            if not (a[3] + inflate < b[1] or b[3] + inflate < a[1]):
                ri, rj = find(remap[i]), find(remap[j])
                if ri != rj:
                    parent[ri] = rj
    clusters: dict[int, list[int]] = {}
    for i in range(len(boxes)):
        clusters.setdefault(find(i), []).append(i)
    big = 0
    for members in clusters.values():
        x0 = min(boxes[m][0] for m in members)
        x1 = max(boxes[m][2] for m in members)
        y0 = min(boxes[m][1] for m in members)
        y1 = max(boxes[m][3] for m in members)
        if (x1 - x0) >= 25.0 and (y1 - y0) >= 12.0:
            big += 1
    return min(big, 4)


def _symmetry(segments: list[tuple[float, float, float, float]], axis_y: float,
              axis_span: float) -> float:
    """Revolution-layout evidence, two regimes of GOST drawings:

    * full outline (both halves inked) → mirror-match ratio of horizontal
      stroke radii: fraction of upper-half radii with a matching lower-half
      stroke within MIRROR_TOL_MM;
    * half-section (only one half inked, typical ГОСТ 3D-half-section) →
      one-sided profile coverage: horizontal ink span on the inked side as a
      fraction of the axis span.
    """
    above = [abs(axis_y - s[1]) for s in segments if s[1] < axis_y - 0.5]
    below = [abs(s[1] - axis_y) for s in segments if s[1] > axis_y + 0.5]
    if above and below:
        return sum(1 for r in above if min(abs(b - r) for b in below) < MIRROR_TOL_MM) / len(above)
    side = above or below
    if not side or axis_span <= 0:
        return 0.0
    span = sum(max(0.0, abs(s[2] - s[0])) for s in segments if (s[1] < axis_y - 0.5) == bool(above))
    return min(1.0, span / axis_span)


# --------------------------------------------------------------------------- #
# vector (PDF)                                                                 #
# --------------------------------------------------------------------------- #
def classify_pdf(path: str | Path) -> Evidence:
    import fitz  # pymupdf

    from core.vectorize import classify_dash

    path = str(path)
    try:
        with fitz.open(path) as doc:
            if doc.page_count == 0:
                return Evidence(path, "UNREADABLE", reason="PDF has 0 pages")
            page = doc.load_page(0)
            words = list(page.get_text("words"))
            drawings = list(page.get_drawings())
            page_w = page.rect.width * MM_PER_PT
    except Exception as exc:
        return Evidence(path, "UNREADABLE", reason=f"fitz failed: {exc.__class__.__name__}: {exc}")

    tokens = [str(w[4]).strip() for w in words if str(w[4]).strip()]
    ev = Evidence(path, "UNREADABLE")
    ev.text_layer = bool(tokens)
    ev.dia_count = _dia_token_count(tokens)
    ev.dim_token_count = _dim_token_count(tokens)

    # horizontal strokes (solid contour or dash-dot) — everything in mm
    solid: list[tuple[float, float, float, float]] = []   # x0,y0,x1,y1
    dashed: list[tuple[float, float, float, float]] = []
    all_boxes: list[tuple[float, float, float, float]] = []
    horiz_all: list[tuple[float, float, float]] = []  # x0, y_mid, x1 (mm), any width
    for drawing in drawings:
        width_pt = drawing.get("width") or 0.0
        is_dash = classify_dash((drawing.get("dashes") or "").strip())
        for item in drawing.get("items", []):
            if item[0] == "re":
                r = item[1]
                all_boxes.append((r.x0 * MM_PER_PT, r.y0 * MM_PER_PT, r.x1 * MM_PER_PT, r.y1 * MM_PER_PT))
                # wide rects contribute their top/bottom edges as horizontal ink
                if r.width >= r.height:
                    y_top, y_bot = r.y0 * MM_PER_PT, r.y1 * MM_PER_PT
                    horiz_all.append((r.x0 * MM_PER_PT, y_top, r.x1 * MM_PER_PT))
                    if (y_bot - y_top) > 0.5:
                        horiz_all.append((r.x0 * MM_PER_PT, y_bot, r.x1 * MM_PER_PT))
                continue
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            x0, y0, x1, y1 = p1.x * MM_PER_PT, p1.y * MM_PER_PT, p2.x * MM_PER_PT, p2.y * MM_PER_PT
            all_boxes.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
            if abs(y1 - y0) <= 0.5:
                horiz_all.append((min(x0, x1), (y0 + y1) / 2.0, max(x0, x1)))
                target = dashed if is_dash else (solid if width_pt >= 1.2 else None)
                if target is not None:
                    target.append((x0, y0, x1, y1))

    if not all_boxes and not tokens:
        ev.reason = "blank page: no stroked geometry and no text"
        return ev

    def _chain_axis(horiz: list[tuple[float, float, float]], page_width: float):
        """GOST centre lines whose dashes/dots are exported as separate thin
        segments carry no dash attribute at all — detect the collinear chain
        itself: ≥4 pieces in one y band, small gaps, long extent."""
        bands: dict[int, list[tuple[float, float]]] = {}
        for x0, y, x1 in horiz:
            bands.setdefault(round(y / CHAIN_Y_BAND_MM), []).append((x0, x1))
        best = None
        for band, segs in bands.items():
            segs.sort()
            if len(segs) < CHAIN_MIN_PIECES:
                continue
            span = segs[-1][1] - segs[0][0]
            if span < CHAIN_AXIS_SPAN * page_width:
                continue
            gaps = [segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1)]
            if gaps and max(gaps) > CHAIN_MAX_GAP_MM:
                continue
            covered = sum(x1 - x0 for x0, x1 in segs)
            if covered / span < CHAIN_MIN_COVERAGE:
                continue
            if best is None or span > best[1]:
                best = (band * CHAIN_Y_BAND_MM, span)
        return best

    # --- axis: longest dashed horizontal span, capped at 1.0
    axis_y = None
    axis_span = 0.0
    sym_segments: list[tuple[float, float, float, float]] = [(x0, y, x1, y) for x0, y, x1 in horiz_all]
    if dashed:
        longest = max(dashed, key=lambda s: abs(s[2] - s[0]))
        axis_span = abs(longest[2] - longest[0])
        ev.axis_score = round(min(1.0, axis_span / (0.45 * page_w)), 3)
        axis_y = (longest[1] + longest[3]) / 2.0
    elif any(abs(s[2] - s[0]) > 0.45 * page_w for s in solid):
        ev.axis_score = 0.3  # long solid horizontal: weak evidence only
    if axis_y is None:
        chain = _chain_axis(horiz_all, page_w)
        if chain is not None:
            axis_y, axis_span = chain
            ev.axis_score = round(min(1.0, axis_span / (CHAIN_AXIS_SPAN * page_w) * 0.6), 3)

    # --- revolution-layout evidence (mirror or one-sided coverage)
    if axis_y is not None:
        ev.symmetry_score = round(_symmetry(sym_segments, axis_y, axis_span), 3)

    ev.views_count = _views_count(all_boxes)

    if ev.dim_token_count == 0 and ev.dia_count == 0:
        ev.verdict = "NO_DIMENSIONS"
        ev.reason = f"no dimension-like tokens ({len(tokens)} text tokens, {ev.dia_count} Ø)"
    elif ev.axis_score >= AXIS_MIN and ev.symmetry_score >= SYMMETRY_MIN and ev.views_count <= 2 \
            and (ev.dia_count >= 1 or ev.dim_token_count >= 2):
        ev.verdict = "BODY_OF_REVOLUTION"
        ev.reason = (f"dash-dot axis {ev.axis_score:.2f}, symmetry {ev.symmetry_score:.2f}, "
                     f"Ø={ev.dia_count}, views={ev.views_count}")
    else:
        ev.verdict = "NOT_SUPPORTED"
        ev.reason = (f"axis={ev.axis_score:.2f} symmetry={ev.symmetry_score:.2f} "
                     f"views={ev.views_count} Ø={ev.dia_count} tokens={ev.dim_token_count}")
    return ev


# --------------------------------------------------------------------------- #
# raster (scans)                                                               #
# --------------------------------------------------------------------------- #
def classify_image(path: str | Path) -> Evidence:
    import cv2
    import numpy as np

    path = str(path)
    ev = Evidence(path, "UNREADABLE")
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        ev.reason = "cv2 cannot decode the image"
        return ev
    h, w = image.shape
    if min(h, w) < MIN_IMAGE_SIDE:
        ev.reason = f"image too small for OCR-grade scan ({w}x{h}px)"
        return ev
    ink = int((image < 200).sum())
    if ink < 0.005 * image.size:
        ev.reason = "blank image (ink < 0.5%)"
        return ev

    # screening on a downscaled copy — verdict-level evidence does not need
    # full acad resolution, and 10 MP Hough transforms take minutes
    scale = min(1.0, 1600.0 / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = image.shape

    binary = (image < 200).astype(np.uint8) * 255
    edges = cv2.Canny(binary, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                            minLineLength=int(0.2 * w), maxLineGap=30)
    horizontal: list[tuple[float, float, float]] = []  # x0, y_mid, span
    if lines is not None:
        for raw in lines:
            x1, y1, x2, y2 = (int(v) for v in raw[0])
            if abs(y2 - y1) <= max(2.0, h * 0.004):
                horizontal.append((min(x1, x2), (y1 + y2) / 2.0, abs(x2 - x1)))

    ev.text_layer = False  # no text layer; OCR is a separate stage
    if horizontal:
        _, axis_y, span = max(horizontal, key=lambda s: s[2])
        ev.axis_score = round(min(0.9, span / (0.6 * w)), 3)  # raster: cap 0.9
        above = int((image[: int(axis_y), :] < 200).sum())
        below = int((image[int(axis_y):, :] < 200).sum())
        total = above + below
        ev.symmetry_score = round((2.0 * min(above, below) / total) if total else 0.0, 3)
    ev.views_count = 1 if horizontal else 0

    if ev.axis_score >= RASTER_AXIS_MIN and ev.symmetry_score >= SYMMETRY_MIN:
        ev.verdict = "BODY_OF_REVOLUTION"
        ev.reason = (f"raster: dominant horizontal stroke (axis~{ev.axis_score:.2f}), "
                     f"ink symmetry {ev.symmetry_score:.2f} — dimension VALUES not screened (no OCR here)")
    else:
        ev.verdict = "NOT_SUPPORTED"
        ev.reason = f"raster: axis~{ev.axis_score:.2f} symmetry={ev.symmetry_score:.2f} — no revolution layout"
    return ev


def classify_file(path: str | Path) -> Evidence:
    """Per-file isolation — a crashing file becomes UNREADABLE evidence,
    never a failed batch (same principle as the pipeline workers)."""
    try:
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            return classify_pdf(path)
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            return classify_image(path)
        return Evidence(str(path), "UNREADABLE", reason=f"unsupported extension: {suffix}")
    except Exception as exc:
        return Evidence(str(path), "UNREADABLE", reason=f"screen crash: {exc.__class__.__name__}: {exc}")


# --------------------------------------------------------------------------- #
# csv                                                                          #
# --------------------------------------------------------------------------- #
CSV_FIELDS = ["id", "path", "verdict", "axis_score", "symmetry_score", "dia_count",
              "dim_token_count", "views_count", "text_layer", "reason"]


def write_csv(rows: list[Evidence], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.csv_row())


def summarize(rows: list[Evidence]) -> str:
    counts = {v: sum(1 for r in rows if r.verdict == v) for v in VERDICTS}
    total = len(rows)
    lines = [f"screened {total} file(s):"]
    for v in VERDICTS:
        pct = counts[v] / total * 100 if total else 0.0
        lines.append(f"  {v:<19} {counts[v]:>5}  ({pct:.1f}%)")
    return "\n".join(lines)


def _iter_corpus(root: Path) -> list[Path]:
    exts = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    files: list[Path] = []
    excluded = 0
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in exts or not p.is_file():
            continue
        # committed test fixtures live under data/corpus/golden/ and are NOT
        # corpus data — they must never enter screen/pipeline metrics
        if "golden" in p.relative_to(root).parts:
            excluded += 1
            continue
        files.append(p)
    if excluded:
        print(f"note: excluded {excluded} committed golden fixture(s) under golden/ (not corpus data)",
              file=sys.stderr)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Screen downloaded corpus files (revolution vs the rest).")
    ap.add_argument("--corpus", required=True, help="corpus root (e.g. data/corpus)")
    ap.add_argument("--out", default=None, help="screening.csv path (default: <corpus>/screening.csv)")
    args = ap.parse_args(argv)

    root = Path(args.corpus)
    files = _iter_corpus(root)
    if not files:
        print(f"no files found under {root} — run core.dataset_fetch first", file=sys.stderr)
        return 3
    rows = []
    for _i, _f in enumerate(files, 1):
        import time as _time
        _t0 = _time.perf_counter()
        rows.append(classify_file(_f))
        print(f"[screen {_i}/{len(files)}] {_f.stem}: {rows[-1].verdict} ({_time.perf_counter() - _t0:.2f}s)", file=sys.stderr)
    out_path = Path(args.out) if args.out else root / "screening.csv"
    write_csv(rows, out_path)
    print(summarize(rows))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
