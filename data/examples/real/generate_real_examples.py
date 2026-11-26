"""Independent generators for the REAL test drawings (Task 2).

These PDFs are produced with reportlab and matplotlib — NOT with PyMuPDF —
so the parser is tested against geometry authored by a different stack
(no shared code, no shared assumptions). Sheet coordinates are designed in
millimetres with Y measured DOWNWARD (matching pymupdf's view of a page).

Files produced in this folder:

    shaft_3step_chamfer_bore.pdf   (a) 3 steps + 2×45° chamfers + Ø12 centre bore, 1:1, A4 landscape
    flange_scale_1_2.pdf           (b) flange Ø100 / bore Ø40 / width 30, scale 1:2, A4 landscape
    rotated_shaft.pdf              (c) vertical-axis shaft, off-centre, text above lines, Ø + R dims, A4 portrait
    bushing_2_1.pdf                (d) bushing Ø20 / bore Ø12 / length 25, scale 2:1, A4 portrait
    scan_test.png                  noisy scan of (a): 2.5° rotation, Gaussian noise, 200 DPI

Each PDF/PNG has a sibling ``*_ground_truth.json`` with true dimensions.
Regenerate everything:  python -m data.examples.real.generate_real_examples
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

# stroke widths (points) — GOST: main line ≥ 0.5 mm, thin ≈ 0.25–0.35 mm
W_MAIN = 1.6
W_THIN = 0.6
W_AXIS = 0.6
FONT = "Helvetica"
FONT_SIZE = 13.0


def _register_cyrillic_font() -> None:
    """Prefer DejaVu Sans (Cyrillic-capable) shipped with matplotlib."""
    global FONT
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import matplotlib
        from pathlib import Path as _P
        candidate = _P(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf" / "DejaVuSans.ttf"
        if candidate.exists():
            pdfmetrics.registerFont(TTFont("DejaVu", str(candidate)))
            FONT = "DejaVu"
    except Exception:
        FONT = "Helvetica"


_register_cyrillic_font()

HERE = Path(__file__).parent


# ------------------------------------------------------------------ helpers

def _mm(v: float) -> float:
    return v * mm


def _Y(page_h_mm: float, y_down_mm: float) -> float:
    """reportlab measures Y bottom-up; our design Y is measured downward."""
    return _mm(page_h_mm - y_down_mm)


def line(c, page_h, x0, y0, x1, y1, width, dash=None):
    c.saveState()
    c.setLineWidth(width)
    if dash:
        c.setDash(dash, 0)
    c.line(_mm(x0), _Y(page_h, y0), _mm(x1), _Y(page_h, y1))
    c.restoreState()


def polyline(c, page_h, points, width, close=False):
    c.saveState()
    c.setLineWidth(width)
    path = c.beginPath()
    path.moveTo(_mm(points[0][0]), _Y(page_h, points[0][1]))
    for x, y in points[1:]:
        path.lineTo(_mm(x), _Y(page_h, y))
    if close:
        path.close()
    c.drawPath(path, fill=0, stroke=1)
    c.restoreState()


def arrow(c, page_h, x, y, angle_rad, size_mm=3.0):
    """Filled triangle arrowhead; parser ignores fill-only paths."""
    tip = (x, y)
    b1 = (x - size_mm * math.cos(angle_rad - 0.42), y - size_mm * math.sin(angle_rad - 0.42))
    b2 = (x - size_mm * math.cos(angle_rad + 0.42), y - size_mm * math.sin(angle_rad + 0.42))
    c.saveState()
    path = c.beginPath()
    path.moveTo(_mm(tip[0]), _Y(page_h, tip[1]))
    path.lineTo(_mm(b1[0]), _Y(page_h, b1[1]))
    path.lineTo(_mm(b2[0]), _Y(page_h, b2[1]))
    path.close()
    c.setFillColorRGB(0, 0, 0)
    c.drawPath(path, fill=1, stroke=0)
    c.restoreState()


def text(c, page_h, x, baseline_y, s, size=FONT_SIZE):
    c.saveState()
    c.setFont(FONT, size)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(_mm(x), _Y(page_h, baseline_y), s)
    c.restoreState()


def vertical_dim(c, page_h, x, y_top, y_bot, arrows=True):
    line(c, page_h, x, y_top, x, y_bot, W_THIN)
    if arrows:
        arrow(c, page_h, x, y_top, math.pi / 2)
        arrow(c, page_h, x, y_bot, -math.pi / 2)


def horizontal_dim(c, page_h, y, x0, x1, arrows=True):
    line(c, page_h, x0, y, x1, y, W_THIN)
    if arrows:
        arrow(c, page_h, x0, y, 0.0)
        arrow(c, page_h, x1, y, math.pi)


def dash_dot_axis(c, page_h, x0, y0, x1, y1):
    line(c, page_h, x0, y0, x1, y1, W_AXIS, dash=[_mm(4), _mm(1.5), _mm(1), _mm(1.5)])


def write_gt(name: str, gt: dict) -> Path:
    path = HERE / f"{name}_ground_truth.json"
    path.write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def chamfer_removed(radius: float, leg: float) -> float:
    """Volume removed from a cylinder end by a 45° chamfer (cone shell)."""
    return math.pi * (radius**2 * leg - (radius**3 - (radius - leg) ** 3) / 3.0)


# ------------------------------------------------------------ case (a)

def gen_a() -> None:
    page_w, page_h = 297.0, 210.0
    c = rl_canvas.Canvas(str(HERE / "shaft_3step_chamfer_bore.pdf"),
                         pagesize=landscape(A4))
    # outline: journals Ø40 / Ø60 / Ø30 with 2×45° chamfers at both ends
    outline = [(20, 87), (22, 85), (100, 85), (100, 75), (160, 75), (160, 90),
               (258, 90), (260, 92), (260, 118), (258, 120), (160, 120), (160, 135),
               (100, 135), (100, 125), (22, 125), (20, 123), (20, 87)]
    polyline(c, page_h, outline, W_MAIN, close=True)
    # bore walls (GOST section convention: visible, main line)
    line(c, page_h, 20, 99, 260, 99, W_MAIN)
    line(c, page_h, 20, 111, 260, 111, W_MAIN)
    dash_dot_axis(c, page_h, 12, 105, 268, 105)

    # diameter dimensions — text above the dim line top
    vertical_dim(c, page_h, 60, 85, 125);  text(c, page_h, 60, 80.5, "Ø40")
    vertical_dim(c, page_h, 130, 75, 135); text(c, page_h, 130, 70.5, "Ø60")
    vertical_dim(c, page_h, 210, 90, 120); text(c, page_h, 210, 85.5, "Ø30")
    # bore diameter — small vertical dim across the bore walls
    vertical_dim(c, page_h, 240, 99, 111); text(c, page_h, 240, 95.5, "Ø12")

    # chamfer leaders + callouts
    line(c, page_h, 21, 86.5, 38, 66, W_THIN);   text(c, page_h, 45, 64.5, "2×45°", size=11)
    line(c, page_h, 259.5, 119, 250, 150, W_THIN); text(c, page_h, 243, 154.5, "2×45°", size=11)

    # overall length
    line(c, page_h, 20, 128, 20, 179, W_THIN)
    line(c, page_h, 260, 123, 260, 179, W_THIN)
    horizontal_dim(c, page_h, 174, 20, 260);     text(c, page_h, 140, 170.5, "240")
    # chain dimensions
    horizontal_dim(c, page_h, 194, 20, 100);     text(c, page_h, 60, 190.5, "80")
    horizontal_dim(c, page_h, 194, 100, 160);    text(c, page_h, 130, 190.5, "60")
    horizontal_dim(c, page_h, 194, 160, 260);    text(c, page_h, 210, 190.5, "100")

    text(c, page_h, 24, 14, "ВАЛ · ДЕМО · Масштаб 1:1", size=9)
    c.showPage()
    c.save()

    base = math.pi * (20**2 * 80 + 30**2 * 60 + 15**2 * 100)
    chamfers = chamfer_removed(20.0, 2.0) + chamfer_removed(15.0, 2.0)
    bore = math.pi * 6**2 * 240
    gt = {
        "part": "Shaft, 3 steps, chamfers 2x45° at both ends, centre through hole",
        "generator": "reportlab", "source_file": "shaft_3step_chamfer_bore.pdf",
        "sheet": {"name": "A4 landscape", "width_mm": page_w, "height_mm": page_h, "scale": 1.0},
        "bore_diameter": 12.0, "chamfer_mm": 2.0,
        "profile_steps": [[20, 100, 40], [100, 160, 60], [160, 260, 30]],
        "expected_length_mm": 240.0,
        "expected_volume_mm3": base - chamfers - bore,
        "dimensions": [
            {"symbol": "DIAMETER", "value": 40.0}, {"symbol": "DIAMETER", "value": 60.0},
            {"symbol": "DIAMETER", "value": 30.0}, {"symbol": "DIAMETER", "value": 12.0},
            {"symbol": "LINEAR", "value": 240.0}, {"symbol": "LINEAR", "value": 80.0},
            {"symbol": "LINEAR", "value": 60.0}, {"symbol": "LINEAR", "value": 100.0},
            {"symbol": "CHAMFER", "value": 2.0}, {"symbol": "CHAMFER", "value": 2.0},
        ],
    }
    write_gt("shaft_3step_chamfer_bore", gt)


# ------------------------------------------------------------ case (b)

def gen_b() -> None:
    page_w, page_h = 297.0, 210.0
    s = 0.5  # drawing scale 1:2
    c = rl_canvas.Canvas(str(HERE / "flange_scale_1_2.pdf"),
                         pagesize=landscape(A4))
    axis_y = 105.0
    x0, x1 = 141.0, 156.0  # drawn width 15 mm = true 30 mm
    r_out, r_in = 100 * s / 2, 40 * s / 2
    polyline(c, page_h, [(x0, axis_y - r_out), (x1, axis_y - r_out),
                         (x1, axis_y + r_out), (x0, axis_y + r_out)], W_MAIN, close=True)
    # bore walls
    line(c, page_h, x0, axis_y - r_in, x1, axis_y - r_in, W_MAIN)
    line(c, page_h, x0, axis_y + r_in, x1, axis_y + r_in, W_MAIN)
    dash_dot_axis(c, page_h, 126, axis_y, 171, axis_y)

    vertical_dim(c, page_h, 148.5, axis_y - r_out, axis_y + r_out)
    text(c, page_h, 148.5, axis_y - r_out - 4.5, "Ø100")
    vertical_dim(c, page_h, 152.5, axis_y - r_in, axis_y + r_in)
    text(c, page_h, 152.5, axis_y - r_in - 4.5, "Ø40", size=11)
    # width dimension
    line(c, page_h, x0, axis_y + r_out + 3, x0, 168, W_THIN)
    line(c, page_h, x1, axis_y + r_out + 3, x1, 168, W_THIN)
    horizontal_dim(c, page_h, 163, x0, x1); text(c, page_h, 148.5, 159.5, "30")

    text(c, page_h, 24, 14, "ФЛАНЕЦ · ДЕМО · Масштаб 1:2", size=9)
    c.showPage()
    c.save()

    gt = {
        "part": "Flange, outer Ø100, bore Ø40, width 30, plotted 1:2 on A4 landscape",
        "generator": "reportlab", "source_file": "flange_scale_1_2.pdf",
        "sheet": {"name": "A4 landscape", "width_mm": page_w, "height_mm": page_h, "scale": 0.5},
        "bore_diameter": 40.0, "chamfer_mm": None,
        "profile_steps": [[0, 30, 100]],
        "expected_length_mm": 30.0,
        "expected_volume_mm3": math.pi * 30.0 * (50.0**2 - 20.0**2),
        "dimensions": [
            {"symbol": "DIAMETER", "value": 100.0},
            {"symbol": "DIAMETER", "value": 40.0},
            {"symbol": "LINEAR", "value": 30.0},
        ],
    }
    write_gt("flange_scale_1_2", gt)


# ------------------------------------------------------------ case (c)

def gen_c() -> None:
    import matplotlib
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    page_w, page_h = 210.0, 297.0
    fig, ax = plt.subplots(figsize=(page_w / 25.4, page_h / 25.4))
    ax.set_xlim(0, page_w)
    ax.set_ylim(page_h, 0)  # Y down
    ax.set_aspect("equal")
    ax.axis("off")
    ax.margins(0)

    BLACK = "#000000"
    # outline polyline (straight parts); top end is a semicircular arc (R12.5)
    pts = [(137.5, 45), (137.5, 95), (125, 95), (125, 135), (135, 135), (135, 185),
           (165, 185), (165, 135), (175, 135), (175, 95), (162.5, 95), (162.5, 45)]
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=BLACK, linewidth=2.0, solid_joinstyle="miter")
    # semicircular top cap (arc — parser ignores curve items by design)
    theta = np.linspace(0, np.pi, 64)
    cap_x = 150 + 12.5 * np.cos(theta)
    cap_y = 45 - 12.5 * np.sin(theta)
    ax.plot(cap_x, cap_y, color=BLACK, linewidth=2.0)

    axis_x = 150.0
    ax.plot([axis_x, axis_x], [22, 200], color=BLACK, linewidth=0.6,
            dashes=[6, 2, 1, 2])

    THIN = 0.8

    def hdim(y, x0, x1):
        ax.plot([x0, x1], [y, y], color=BLACK, linewidth=THIN)
        for x, ang in ((x0, 0.0), (x1, math.pi)):
            ax.add_patch(Polygon([(x, y),
                                  (x - 3.0 * math.cos(ang - 0.42), y - 3.0 * math.sin(ang - 0.42)),
                                  (x - 3.0 * math.cos(ang + 0.42), y - 3.0 * math.sin(ang + 0.42))],
                                 color=BLACK))

    def vdim(x, y0, y1):
        ax.plot([x, x], [y0, y1], color=BLACK, linewidth=THIN)
        for y, ang in ((y0, math.pi / 2), (y1, -math.pi / 2)):
            ax.add_patch(Polygon([(x, y),
                                  (x - 3.0 * math.cos(ang - 0.42), y - 3.0 * math.sin(ang - 0.42)),
                                  (x - 3.0 * math.cos(ang + 0.42), y - 3.0 * math.sin(ang + 0.42))],
                                 color=BLACK))

    def txt(x, y, s, size=12, ha="center"):
        ax.text(x, y, s, fontsize=size, ha=ha, va="center", color=BLACK)

    # diameter dimensions — text above the dim line
    hdim(70, 137.5, 162.5);  txt(150, 65.0, "Ø25")
    hdim(115, 125, 175);     txt(150, 110.0, "Ø50")
    hdim(160, 135, 165);     txt(150, 155.0, "Ø30")
    # R dimension of the top round — leader + shelf to the cap arc
    ax.plot([146, 100], [33.5, 21], color=BLACK, linewidth=THIN)
    ax.plot([100, 82], [21, 21], color=BLACK, linewidth=THIN)
    txt(70, 18.3, "R12.5", size=12)
    # overall length (apex -> base) — extension lines from the cap tip and the base
    ax.plot([150, 197], [32.5, 32.5], color=BLACK, linewidth=THIN)
    ax.plot([165, 197], [185, 185], color=BLACK, linewidth=THIN)
    vdim(192, 32.5, 185);    txt(181, 27.0, "152.5")
    # chain dimensions — first leg includes the cap height (apex -> first shoulder)
    vdim(118, 32.5, 95);     txt(118, 27.0, "62.5")
    vdim(105, 95, 135);      txt(105, 89.5, "40")
    vdim(118, 135, 185);     txt(118, 129.5, "50")

    txt(15, 258, "ВАЛ · ДЕМО · Масштаб 1:1", size=9, ha="left")
    txt(15, 268, "вертикальная ось", size=7, ha="left")

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(HERE / "rotated_shaft.pdf", format="pdf")
    plt.close(fig)

    base = math.pi * (12.5**2 * 50 + 25.0**2 * 40 + 15.0**2 * 50)
    cap = (2.0 / 3.0) * math.pi * 12.5**3
    gt = {
        "part": "Vertical-axis shaft, off-centre on A4 portrait, round top end (R12.5)",
        "generator": "matplotlib", "source_file": "rotated_shaft.pdf",
        "sheet": {"name": "A4 portrait", "width_mm": page_w, "height_mm": page_h,
                  "scale": 1.0, "orientation": "vertical-axis"},
        "bore_diameter": None, "chamfer_mm": None,
        "profile_steps": [[45, 95, 25], [95, 135, 50], [135, 185, 30]],
        "expected_length_mm": 152.5,
        "expected_volume_mm3": base + cap,
        "cap": "hemisphere R12.5 on top of the Ø25 neck",
        "dimensions": [
            {"symbol": "DIAMETER", "value": 25.0}, {"symbol": "DIAMETER", "value": 50.0},
            {"symbol": "DIAMETER", "value": 30.0}, {"symbol": "RADIUS", "value": 12.5},
            {"symbol": "LINEAR", "value": 152.5}, {"symbol": "LINEAR", "value": 62.5},
            {"symbol": "LINEAR", "value": 40.0}, {"symbol": "LINEAR", "value": 50.0},
        ],
    }
    write_gt("rotated_shaft", gt)


# ------------------------------------------------------------ case (d)

def gen_d() -> None:
    page_w, page_h = 210.0, 297.0
    c = rl_canvas.Canvas(str(HERE / "bushing_2_1.pdf"),
                         pagesize=portrait(A4))
    axis_y = 148.5
    # drawn at 2:1: true Ø20→drawn Ø40, true bore Ø12→drawn Ø24, true length 25→drawn 50
    r_out, r_in, half_len = 20.0, 12.0, 25.0
    x0, x1 = 105 - half_len, 105 + half_len
    polyline(c, page_h, [(x0, axis_y - r_out), (x1, axis_y - r_out),
                         (x1, axis_y + r_out), (x0, axis_y + r_out)], W_MAIN, close=True)
    line(c, page_h, x0, axis_y - r_in, x1, axis_y - r_in, W_MAIN)
    line(c, page_h, x0, axis_y + r_in, x1, axis_y + r_in, W_MAIN)
    dash_dot_axis(c, page_h, x0 - 15, axis_y, x1 + 15, axis_y)

    vertical_dim(c, page_h, 105, axis_y - r_out, axis_y + r_out)
    text(c, page_h, 105, axis_y - r_out - 4.5, "Ø20")
    vertical_dim(c, page_h, 118, axis_y - r_in, axis_y + r_in)
    text(c, page_h, 118, axis_y - r_in - 4.5, "Ø12", size=11)
    line(c, page_h, x0, axis_y + r_out + 3, x0, 210, W_THIN)
    line(c, page_h, x1, axis_y + r_out + 3, x1, 210, W_THIN)
    horizontal_dim(c, page_h, 205, x0, x1); text(c, page_h, 105, 201.5, "25")

    text(c, page_h, 15, 260, "ВТУЛКА · ДЕМО · Масштаб 2:1", size=9)
    c.showPage()
    c.save()

    gt = {
        "part": "Bushing, outer Ø20, bore Ø12, length 25, plotted 2:1 on A4 portrait",
        "generator": "reportlab", "source_file": "bushing_2_1.pdf",
        "sheet": {"name": "A4 portrait", "width_mm": page_w, "height_mm": page_h, "scale": 0.5},
        "bore_diameter": 12.0, "chamfer_mm": None,
        "profile_steps": [[0, 25, 20]],
        "expected_length_mm": 25.0,
        "expected_volume_mm3": math.pi * 25.0 * (10.0**2 - 6.0**2),
        "dimensions": [
            {"symbol": "DIAMETER", "value": 20.0},
            {"symbol": "DIAMETER", "value": 12.0},
            {"symbol": "LINEAR", "value": 25.0},
        ],
    }
    write_gt("bushing_2_1", gt)


# ------------------------------------------------------------ scan PNG

def gen_scan() -> None:
    import cv2
    import fitz
    from PIL import Image

    with fitz.open(HERE / "shaft_3step_chamfer_bore.pdf") as doc:
        pix = doc.load_page(0).get_pixmap(dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        elif pix.n != 3:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)

    h, w = img.shape[:2]
    # The scan represents a cropped view scan: blank out the sheet's title
    # caption before adding noise (geometry/OCR is what is under test here;
    # a title block would just feed Cyrillic glyph strokes into the geometry)
    # measured caption glyph extent in this render: x 0-328px, y 128-161px
    cv2.rectangle(img, (0, 70), (400, 125), (255, 255, 255), thickness=-1)

    angle = 2.5
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    rng = np.random.default_rng(20240521)
    noise = rng.normal(0.0, 16.0, rotated.shape).astype(np.float32)
    noisy = np.clip(rotated.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    noisy = cv2.GaussianBlur(noisy, (3, 3), 0.6)

    Image.fromarray(noisy).save(HERE / "scan_test.png", dpi=(200, 200))

    source_gt = json.loads((HERE / "shaft_3step_chamfer_bore_ground_truth.json").read_text(encoding="utf-8"))
    gt = dict(source_gt)
    gt["generator"] = "render(source PDF, 200 DPI) + rotate 2.5° + gaussian noise sigma=16 + slight blur"
    gt["source_file"] = "scan_test.png"
    gt["scan"] = {"dpi": 200, "rotation_deg": 2.5, "noise_sigma": 16.0,
                  "note": "OCR recall may be imperfect; unresolved dims MUST be flagged uncertain, never invented"}
    write_gt("scan_test", gt)




def gen_scan_harsh() -> None:
    """Second synthetic scan: different rotation and much heavier noise.

    Exists to prove the real-scan harness (core/benchmark_real.py) works on
    ANY scan, not just scan_test.png — same part geometry, worse acquisition.
    Deterministic: seeded RNG (seed 20240522), 200 DPI, -4.0 degrees,
    Gaussian noise sigma=24, slightly heavier blur.
    """
    import cv2
    import fitz
    from PIL import Image

    with fitz.open(HERE / "shaft_3step_chamfer_bore.pdf") as doc:
        pix = doc.load_page(0).get_pixmap(dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        elif pix.n != 3:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)

    h, w = img.shape[:2]
    # same caption blank-out trick as gen_scan (title feeds glyph strokes, not geometry)
    cv2.rectangle(img, (0, 70), (400, 125), (255, 255, 255), thickness=-1)

    angle = -4.0
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    rng = np.random.default_rng(20240522)
    noise = rng.normal(0.0, 24.0, rotated.shape).astype(np.float32)
    noisy = np.clip(rotated.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    noisy = cv2.GaussianBlur(noisy, (3, 3), 0.9)

    Image.fromarray(noisy).save(HERE / "scan_test_harsh.png", dpi=(200, 200))

    source_gt = json.loads((HERE / "shaft_3step_chamfer_bore_ground_truth.json").read_text(encoding="utf-8"))
    gt = dict(source_gt)
    gt["generator"] = "render(source PDF, 200 DPI) + rotate -4.0 deg + gaussian noise sigma=24 + blur 0.9"
    gt["source_file"] = "scan_test_harsh.png"
    gt["scan"] = {"dpi": 200, "rotation_deg": -4.0, "noise_sigma": 24.0,
                  "note": "harsh acquisition; harness must still run end-to-end"}
    write_gt("scan_test_harsh", gt)


def main() -> None:
    gen_a(); gen_b(); gen_c(); gen_d(); gen_scan(); gen_scan_harsh()
    print("real examples written to", HERE)


if __name__ == "__main__":
    main()
