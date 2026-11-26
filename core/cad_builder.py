"""Build a solid of revolution from a verified half-profile and export it.

The profile (list of :class:`ProfilePoint`, millimetres, monotonic in x) is
revolved 360° around the X axis with CadQuery (OpenCASCADE B-rep kernel).
An optional central through-bore can be cut (flanges / bushings / rings).

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
    if abs(xs[0] - profile[0].x) > 1e-9 or abs(max(xs) - min(xs)) <= 0:
        raise ValueError("Profile has zero length")


def build_solid(
    profile: list[ProfilePoint],
    dimensions: list[Dimension] | None = None,
    bore_diameter: float | None = None,
) -> cq.Workplane:
    """Build the solid of revolution; return the CadQuery Workplane with one solid.

    ``bore_diameter``: optional central through hole (mm), e.g. 20 for Ø20.
    ``dimensions``: accepted for interface stability (v2 will consume confirmed
    dimensions for chamfers / threads); unused for v1 geometry.
    """
    _validate_profile(profile)

    x_min = profile[0].x
    x_max = profile[-1].x

    # half-profile polygon, closed on the axis: (x_min,0) → surfaces… → (x_max,0)
    pts = [(p.x, p.r) for p in profile]
    if pts[0][1] != 0.0:
        pts.insert(0, (x_min, 0.0))
    if pts[-1][1] != 0.0:
        pts.append((x_max, 0.0))

    solid = (
        cq.Workplane("XY")
        .polyline(pts)
        .close()
        .revolve(360.0, axisStart=(0.0, 0.0, 0.0), axisEnd=(1.0, 0.0, 0.0))
    )

    if bore_diameter is not None:
        if bore_diameter <= 0:
            raise ValueError("bore_diameter must be positive")
        length = x_max - x_min
        bore = (
            cq.Workplane("YZ")  # plane normal = +X, so the hole axis is the revolution axis
            .circle(bore_diameter / 2.0)
            .extrude(length)
            .translate((x_min, 0, 0))
        )
        solid = solid.cut(bore)
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
    _ = Symbol  # kept for future chamfer/thread consumption
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
