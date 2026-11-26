"""Generate the 30-file offline golden set (Part 5, Tier C mechanism).

These are SYNTHETIC but ANALYTICALLY VERIFIED fixtures: the expected
volume is computed exactly from the revolved stepped profile (sum of
cylinders), never measured with the pipeline. ``provenance`` is
``synthetic-generated`` in every JSON. They exist so CI can catch geometry
regressions offline — they are NOT a substitute for the 30 real,
hand-verified drawings called for by the task (see docs/CORPUS_BENCHMARK.md;
real goldens require the corpus download, which was impossible from the
build sandbox — see docs/DATA_SOURCES.md).

Deterministic: fixed seed. NOTE: reportlab embeds a creation timestamp, so
file bytes differ between runs; the GT JSON does not depend on timestamps.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas

MM = 72.0 / 25.4  # points per mm
HERE = Path(__file__).resolve().parent


def stepped_volume(steps: list[tuple[float, float]]) -> float:
    """Volume of a stepped body of revolution (sum of cylinders).

    steps: [(x_end, radius)], contiguous, starting at x=0.
    """
    total = 0.0
    x0 = 0.0
    for x1, r in steps:
        total += math.pi * r * r * (x1 - x0)
        x0 = x1
    return total


def draw_golden(path: Path, steps: list[tuple[float, float]], title: str) -> None:
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    page_w, page_h = landscape(A4)
    axis_y = page_h * 0.52
    x_origin = 60.0
    total_len = steps[-1][0]

    # ---- contour: thick stroke (parser treats width >= 1.2pt as contour) ----
    # NB: the parser keeps the half-profile with y < axis_y in fitz coordinates,
    # which is the visually UPPER half — draw the half-profile above the axis.
    c.setLineWidth(1.6)
    c.setDash([], 0)
    # left end face
    c.line(x_origin, axis_y, x_origin, axis_y + steps[0][1] * MM)
    # horizontal segments
    x_bounds = [0.0] + [x for x, _ in steps]
    for i, r in enumerate([r for _, r in steps]):
        xa, xb = x_bounds[i], x_bounds[i + 1]
        y = axis_y + r * MM
        c.line(x_origin + xa * MM, y, x_origin + xb * MM, y)
    # vertical shoulders between consecutive steps
    for i in range(1, len(steps)):
        x = x_origin + steps[i - 1][0] * MM
        y0, y1 = axis_y + steps[i][1] * MM, axis_y + steps[i - 1][1] * MM
        c.line(x, min(y0, y1), x, max(y0, y1))
    # right end face
    x_end = x_origin + total_len * MM
    c.line(x_end, axis_y, x_end, axis_y + steps[-1][1] * MM)

    # ---- GOST dash-dot axis ----
    c.setLineWidth(0.6)
    c.setDash([8, 3, 1, 3], 0)
    c.line(x_origin - 40, axis_y, x_end + 40, axis_y)
    c.setDash([], 0)

    # ---- dimension texts: Ø of each step, overall length below axis ----
    c.setFont("Helvetica", 11)
    for i, (x1, r) in enumerate(steps):
        xa = 0.0 if i == 0 else steps[i - 1][0]
        cx = x_origin + (xa + x1) / 2.0 * MM
        c.drawCentredString(cx, axis_y + r * MM + 10, f"Ø{2 * r:g}")
    c.drawCentredString(x_origin + total_len * MM / 2, axis_y - 24, f"{total_len:g}")

    c.setFont("Helvetica", 8)
    c.drawString(60, 30, title)
    c.showPage()
    c.save()


def main() -> None:
    rng = random.Random(20261126)
    HERE.mkdir(parents=True, exist_ok=True)
    written = 0
    for i in range(1, 31):
        n_steps = rng.choice([2, 2, 3, 3, 4, 4, 5])
        radii = [rng.choice([6.0, 7.5, 9.0, 10.5, 12.0, 13.5, 15.0, 16.5, 18.0, 19.5, 21.0]) for _ in range(n_steps)]
        lengths = [rng.choice([20.0, 25.0, 30.0, 35.0, 40.0, 45.0]) for _ in range(n_steps)]
        steps: list[tuple[float, float]] = []
        x = 0.0
        for length, r in zip(lengths, radii):
            x += length
            steps.append((round(x, 1), r))

        total_len = steps[-1][0]
        volume = stepped_volume(steps)
        diameter = 2 * max(r for _, r in steps)

        pdf_name = f"golden_{i:03d}.pdf"
        draw_golden(HERE / pdf_name, steps, f"golden-{i:03d} (synthetic)")

        record = {
            "schema": "drawtostep.golden.v1",
            "id": f"golden-{i:03d}",
            "file": pdf_name,
            "provenance": "synthetic-generated",
            "generated_by": "data/corpus/golden/generate_golden.py",
            "generator_seed": 20261126,
            "verified_by": "analytic (stepped body of revolution: exact cylinder-sum volume, exact bbox)",
            "verified_at": "2026-11-26",
            "drawing": {
                "steps": [{"x_end_mm": x1, "radius_mm": r} for x1, r in steps],
                "total_length_mm": total_len,
            },
            "expected": {
                "dimensions": (
                    [{"symbol": "DIAMETER", "value_mm": 2 * r} for _, r in steps]
                    + [{"symbol": "LINEAR", "value_mm": total_len}]
                ),
                "volume_mm3": round(volume, 1),
                "bbox_mm": {"length": total_len, "diameter": diameter},
            },
        }
        (HERE / pdf_name).with_suffix(".json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written += 1
    print(f"wrote {written} golden pairs to {HERE}")


if __name__ == "__main__":
    main()
