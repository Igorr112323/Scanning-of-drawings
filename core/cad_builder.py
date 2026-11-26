"""Build a solid of revolution from a verified half-profile and export it.

The profile (list of :class:`ProfilePoint`, millimetres, monotonic in x) is
revolved 360° around the X axis with CadQuery (OpenCASCADE B-rep kernel).

Features supported in v1.1:
- Centre through-hole (hollow body): pass ``bore_diameter`` (mm) — detected
  automatically by the parser from inner-wall contour lines, or given by the
  caller. The bore runs the full length of the part.
- 45° chamfers on the outer end corners: pass a confirmed ``CHAMFER``
  dimension (e.g. "2×45°") in ``dimensions`` — the end corners of the
  half-profile are cut back by the chamfer leg before revolving.
- Both are composited: chamfered ends + bore, all in one exact B-rep.

No approximations and no invented geometry: every radius and length comes
from the user-confirmed drawing profile. If the profile is empty or invalid
we raise — we never build "something plausible".
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from core.models import Dimension, ProfilePoint, Symbol


def _validate_profile(profile: list[ProfilePoint]) -> None:
    if not profile or len(profile) < 4:
        raise ValueError("Profile too small — expected at least a start/end pair and one surface")
    xs = [p.x for p in profile]
    if any(p.r < 0 for p in profile):
        raise ValueError("Profile radius must be non-negative")
    if abs(max(xs) - min(xs)) <= 0:
        raise ValueError("Profile has zero length")


def _chamfer_leg(dimensions: list[Dimension] | None) -> float | None:
    """Chamfer leg (mm) from confirmed CHAMFER dimensions; None otherwise."""
    if not dimensions:
        return None
    legs = [
        d.value for d in dimensions
        if d.symbol is Symbol.CHAMFER and not d.is_uncertain and d.value > 0
    ]
    return max(legs) if legs else None


def _apply_chamfers(pts: list[tuple[float, float]], leg: float) -> list[tuple[float, float]]:
    """Cut 45° chamfers on the outer end corners of the half-profile.

    ``pts`` is the revolve half-polygon including the axis-closing zero rows:
    [(x_min, 0), (x_min, r_left), …shoulders…, (x_max, r_right), (x_max, 0)].
    An end whose first/last surface edge is already diagonal (a chamfer drawn
    in the outline) is left untouched — never cut twice. Legs are clamped
    per end to the smallest end face they touch.
    """
    zero_left = bool(pts) and pts[0][1] == 0.0
    zero_right = bool(pts) and pts[-1][1] == 0.0
    body = list(pts[1:] if zero_left else pts)
    if zero_right:
        body = body[:-1]
    if len(body) < 2:
        return pts
    x_min, x_max = body[0][0], body[-1][0]
    r_left, r_right = body[0][1], body[-1][1]
    if r_left <= 0 or r_right <= 0:
        return pts

    # distance from each end face to the nearest shoulder along the axis
    len_left = next((p[0] - x_min for p in body[1:] if p[0] - x_min > 1e-9), x_max - x_min)
    len_right = next((x_max - p[0] for p in reversed(body[:-1]) if x_max - p[0] > 1e-9), x_max - x_min)
    c_left = min(leg, 0.8 * r_left, 0.45 * len_left)
    c_right = min(leg, 0.8 * r_right, 0.45 * len_right)

    # LEFT end: already drawn as a diagonal edge → keep as-is
    left_diagonal = body[1][0] > x_min + 1e-9 and abs(body[1][1] - body[0][1]) > 0.05
    if not left_diagonal and c_left > 0:
        body = [(x_min, r_left - c_left), (x_min + c_left, r_left)] + body[1:]

    # RIGHT end (indices shifted by the left cut, if any)
    right_diagonal = body[-1][0] > body[-2][0] + 1e-9 and abs(body[-1][1] - body[-2][1]) > 0.05
    if not right_diagonal and c_right > 0:
        body = body[:-1] + [(body[-1][0] - c_right, r_right), (body[-1][0], r_right - c_right)]

    if zero_left:
        body = [pts[0]] + body
    if zero_right:
        body = body + [pts[-1]]
    return body


def build_solid(
    profile: list[ProfilePoint],
    dimensions: list[Dimension] | None = None,
    bore_diameter: float | None = None,
    chamfer_mm: float | None = None,
) -> cq.Workplane:
    """Build the solid of revolution; return the CadQuery Workplane with one solid.

    ``dimensions``: confirmed dimensions; CHAMFER entries are applied as 45°
    end chamfers. ``bore_diameter``: central through hole in mm (hollow body).
    ``chamfer_mm``: explicit chamfer leg override (mm); otherwise inferred
    from confirmed CHAMFER dimensions.
    """
    _validate_profile(profile)

    x_min, x_max = profile[0].x, profile[-1].x
    r_in = (bore_diameter or 0.0) / 2.0
    if bore_diameter is not None:
        if bore_diameter <= 0:
            raise ValueError("bore_diameter must be positive")
        min_feature_r = min(p.r for p in profile if p.r > 0)
        if r_in >= min_feature_r:
            raise ValueError(
                f"bore Ø{bore_diameter:g} exceeds the smallest feature radius "
                f"R{min_feature_r:g} — refusing to build"
            )

    # half-profile polygon including axis-closing zero rows
    pts = [(p.x, p.r) for p in profile]
    if pts[0][1] != 0.0:
        pts.insert(0, (x_min, 0.0))
    if pts[-1][1] != 0.0:
        pts.append((x_max, 0.0))

    leg = chamfer_mm if chamfer_mm is not None else _chamfer_leg(dimensions)
    if leg:
        pts = _apply_chamfers(pts, leg)

    if r_in > 0.0:
        # hollow: outer faces + bore walls, closed on the bore radius
        top = pts[1:-1]  # drop the axis zero rows
        polygon = [(x_min, r_in), *top, (x_max, r_in)]
    else:
        polygon = pts

    solid = (
        cq.Workplane("XY")
        .polyline(polygon)
        .close()
        .revolve(360.0, axisStart=(0.0, 0.0, 0.0), axisEnd=(1.0, 0.0, 0.0))
    )
    return solid


def build_from_drawing(
    profile: list[ProfilePoint],
    confirmed_dimensions: list[Dimension],
    bore_diameter: float | None = None,
) -> cq.Workplane:
    """Convenience wrapper: refuse to build if any dimension is unconfirmed.

    Raises ValueError if ``confirmed_dimensions`` still contains
    ``is_uncertain`` entries — the UI must collect user confirmation first.
    """
    unconfirmed = [d for d in confirmed_dimensions if d.is_uncertain]
    if unconfirmed:
        labels = ", ".join(d.raw_text for d in unconfirmed)
        raise ValueError(f"Нельзя построить 3D: не подтверждены размеры: {labels}")
    return build_solid(profile, confirmed_dimensions, bore_diameter=bore_diameter)


def export_step(shape: cq.Workplane, path: str | Path) -> Path:
    """Export a B-rep STEP file (opens in FreeCAD / KOMPAS / SolidWorks)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path), exportType="STEP")
    return path


def export_stl(shape: cq.Workplane, path: str | Path, tolerance: float = 0.1) -> Path:
    """Export an STL mesh for 3D printing/inspection (linear tolerance in mm)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path), exportType="STL", tolerance=tolerance)
    return path


def find_bore_dimension(dimensions: list[Dimension]) -> float | None:
    """Heuristic helper for the UI: a DIAMETER dim whose raw text carries a
    bore hint ('ОТВ', 'OTV', 'BORE') is the central hole. None if unsure —
    the user decides, we never auto-pick a diameter as a bore."""
    for d in dimensions:
        if d.symbol is Symbol.DIAMETER and any(
            hint in d.raw_text.upper() for hint in ("ОТВ", "OTV", "BORE")
        ):
            return d.value
    return None
