"""Ø recovery via geometry — propose, never auto-apply.

RapidOCR systematically drops the Ø glyph ("Ø40" → "040"). The parser already
links such zero-led texts to their leaders, but the printed value can be
cross-checked against the measured revolution geometry: at the leader station
the drawn strokes sit at ±r around the axis, so the diameter is 2·r.

Rule (documented in docs/ARCHITECTURE.md):
    If a zero-led DIAMETER text is linked to a leader AND the printed value
    matches *any* geometry-measured diameter at the station (outer surfaces
    and/or bore inner walls, taken from the axis-referenced stroke positions
    and the extracted profile) within scan tolerance —
    the dimension is re-emitted as "Ø<value>" with ``confidence = 0.85``,
    ``is_uncertain = True`` (never auto-applied) and
    ``proposed_by_geometry = True``. The UI then pre-fills the editor and the
    user needs ONE click to confirm.

    If nothing matches — nothing is proposed (the dimension stays uncertain,
    e.g. geometry 55 vs printed 060 stays "060" for the user to decide).
"""

from __future__ import annotations

import re
from dataclasses import replace

from core.models import Dimension, Drawing, ElementType, Symbol

# zero-led integer, no decimal dot: "060" — RapidOCR lost the Ø glyph
_ZERO_LED = re.compile(r"^0\d{1,4}$")

#: absolute floor for the diameter tolerance (raster measurement noise)
_MIN_TOL_MM = 0.75
#: relative tolerance vs printed value
_REL_TOL = 0.02
#: half-width of the station window used to gather strokes, in mm
_STATION_HALF_MM = 6.0


def _axis_y(drawing: Drawing) -> float | None:
    for e in drawing.elements:
        if e.type is ElementType.AXIS and len(e.points) == 2:
            (ax, ay), (bx, by) = e.points
            if abs(by - ay) <= 0.18 * abs(bx - ax):
                return (ay + by) / 2.0
    return None


def measured_diameters(drawing: Drawing, x: float) -> list[float]:
    """All diameters at station ``x`` (mm) indicated by drawn strokes.

    Collects near-horizontal strokes spanning the station and the profile's
    surface radii; every measurement is referenced to the revolution axis.
    Returns deduplicated diameters (mm), outer surfaces and bore walls alike.
    """
    axis_y = _axis_y(drawing)
    if axis_y is None:
        return []

    diameters: list[float] = []

    for e in drawing.elements:
        if e.type not in (ElementType.CONTOUR, ElementType.DIMENSION_LINE, ElementType.AXIS):
            continue
        if len(e.points) != 2:
            continue
        (ax, ay), (bx, by) = e.points
        dx = abs(bx - ax)
        if dx < 1.0:
            continue
        if abs(by - ay) > 0.18 * dx:
            continue
        if min(ax, bx) - _STATION_HALF_MM > x or max(ax, bx) + _STATION_HALF_MM < x:
            continue
        y_mid = (ay + by) / 2.0
        d = 2.0 * abs(y_mid - axis_y)
        if d >= 3.0:  # ignore the axis itself and slivers
            diameters.append(d)

    for p in drawing.profile:
        if p.r > 1.5:
            diameters.append(2.0 * p.r)

    if drawing.bore_diameter:
        diameters.append(drawing.bore_diameter)

    diameters.sort()
    deduped: list[float] = []
    for d in diameters:
        if deduped and d - deduped[-1] <= 0.5:
            continue
        deduped.append(d)
    return deduped


def propose_geometry_bound_diameters(dimensions: list[Dimension],
                                     drawing: Drawing) -> list[Dimension]:
    """Re-emit zero-led DIAMETER dimensions proposed from measured geometry.

    Proposals keep the printed value (RapidOCR did NOT hallucinate it — it
    only lost the Ø glyph) and always stay uncertain/unconfirmed: the user
    confirms with one click, nothing is auto-applied.
    """
    axis_y = _axis_y(drawing)
    if axis_y is None:
        return dimensions

    out: list[Dimension] = []
    for d in dimensions:
        if (d.symbol is Symbol.DIAMETER and _ZERO_LED.match(d.raw_text.strip())
                and d.linked_element_id and d.anchor is not None):
            measured = measured_diameters(drawing, d.anchor[0])
            tol = max(_MIN_TOL_MM, _REL_TOL * d.value)
            if any(abs(m - d.value) <= tol for m in measured):
                value = int(d.value) if float(d.value).is_integer() else d.value
                out.append(replace(
                    d,
                    raw_text=f"Ø{value}",
                    confidence=0.85,  # boundary — stays uncertain, needs confirm
                    is_uncertain=True,
                    proposed_by_geometry=True,
                ))
                continue
        out.append(d)
    return out
