"""Constraint solver: drawing-scale inference and dimension consistency checks.

GOST drawings are frequently plotted at a scale (1:2, 1:5, …), so the geometry
extracted from the sheet is NOT necessarily in millimetres while the printed
dimension text IS. This solver:

1. Estimates the sheet scale from the dimensions themselves — diameter
   dimensions are matched against the cylinder-surface radii found in the
   profile: scale = median(dim / (2·r)).
2. Scales the profile to true millimetres (never edits values itself).
3. Verifies every non-uncertain dimension against the scaled profile:
   - DIAMETER / RADIUS  → must match one of the feature diameters;
   - LINEAR             → must match the overall length or one of the step
                          widths (differences of profile breakpoints).
4. Reports contradictions. Uncertain dimensions are NOT used for solving —
   they are skipped and listed as warnings (the user confirms them in the UI
   before 3D generation; contradictions of severity "error" block generation).

Nothing is invented here: a dimension that matches nothing is a contradiction,
never a silent correction.
"""

from __future__ import annotations

import math

from core.models import (
    Contradiction,
    Dimension,
    ProfilePoint,
    Symbol,
)

_DIAMETER_TOL_MM = 0.05
_LINEAR_TOL_MM = 0.05


def _feature_diameters(profile: list[ProfilePoint]) -> list[float]:
    radii = sorted({round(p.r, 6) for p in profile if p.r > 0.0})
    return [2.0 * r for r in radii]


def _feature_widths(profile: list[ProfilePoint]) -> list[float]:
    knots = sorted({p.x for p in profile})
    widths = [b - a for a, b in zip(knots, knots[1:]) if b - a > 0.01]
    total = (max(knots) - min(knots)) if knots else 0.0
    return widths + ([total] if total > 0 else [])


# GOST 2.302 allowed drawing scales (as ratio true_size / plotted_size).
# Drawing-scale inference is restricted to these — anything else would just be
# fitting arithmetic to noise. 1.0 (1:1) wins ties, as it should.
_GOST_SCALES = [0.02, 0.025, 0.04, 0.05, 0.0667, 0.1, 0.2, 0.25, 0.4, 0.5,
                1.0,
                2.0, 2.5, 4.0, 5.0, 10.0, 15.0, 20.0, 25.0, 40.0, 50.0]


def _estimate_scale(dimensions: list[Dimension], profile: list[ProfilePoint]) -> float:
    """Pick the GOST scale that satisfies the most dimensions (1.0 on ties)."""
    if not dimensions or not profile:
        return 1.0
    diameters = _feature_diameters(profile)
    widths = _feature_widths(profile)  # step widths + overall length
    diameter_dims = [d for d in dimensions if d.symbol is Symbol.DIAMETER]
    linear_dims = [d for d in dimensions if d.symbol is Symbol.LINEAR]

    def votes(scale: float) -> int:
        v = 0
        for d in diameter_dims:
            if diameters and min(abs(scale * f - d.value) for f in diameters) <= max(
                    _DIAMETER_TOL_MM, 0.001 * d.value):
                v += 1
        for d in linear_dims:
            if widths and min(abs(scale * w - d.value) for w in widths) <= _LINEAR_TOL_MM:
                v += 1
        return v

    scored = [(s, votes(s)) for s in _GOST_SCALES]
    best_votes = max(v for _, v in scored)
    return min((s for s, v in scored if v == best_votes), key=lambda s: (abs(s - 1.0), s))


def solve_constraints(
    dimensions: list[Dimension],
    profile: list[ProfilePoint],
) -> tuple[list[ProfilePoint], list[Contradiction]]:
    """Verify dimensions against the profile; return (scaled_profile, contradictions).

    ``scaled_profile`` is the profile converted to true millimetres (identity
    when the drawing is plotted 1:1). The returned profile is always a copy —
    inputs are not mutated.
    """
    contradictions: list[Contradiction] = []
    if not profile:
        contradictions.append(Contradiction(
            message="Профиль детали не распознан (ожидается тело вращения с одной главной осью)",
            severity="error",
        ))
        return [], contradictions

    usable = [d for d in dimensions if not d.is_uncertain]
    for d in dimensions:
        if d.is_uncertain:
            contradictions.append(Contradiction(
                message=f"Размер {d.raw_text!r} не подтверждён пользователем и исключён из проверки",
                dimension_ids=[d.id], severity="warning",
            ))

    scale = _estimate_scale(usable, profile)
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    scale = min(max(scale, 0.05), 20.0)

    scaled = [ProfilePoint(p.x * scale, p.r * scale) for p in profile]

    feature_d = _feature_diameters(scaled)
    feature_w = _feature_widths(scaled)
    total_length = (max(p.x for p in scaled) - min(p.x for p in scaled)) if scaled else 0.0

    for dim in usable:
        if dim.symbol in (Symbol.DIAMETER, Symbol.RADIUS, Symbol.THREAD):
            target = dim.value if dim.symbol is Symbol.DIAMETER else dim.value * 2.0
            if not feature_d:
                contradictions.append(Contradiction(
                    message=f"Нет цилиндрических поверхностей для размера {dim.raw_text!r}",
                    dimension_ids=[dim.id], severity="error"))
                continue
            nearest = min(feature_d, key=lambda f: abs(target - f))
            if abs(target - nearest) > max(_DIAMETER_TOL_MM, 0.001 * dim.value):
                contradictions.append(Contradiction(
                    message=(f"Размер {dim.raw_text!r} = {dim.value:g} мм не совпадает "
                             f"ни с одной поверхностью вращения (ближайшая Ø{nearest:g} мм)"),
                    dimension_ids=[dim.id], severity="error"))
        elif dim.symbol is Symbol.LINEAR:
            candidates = feature_w + [total_length]
            if not candidates or min(abs(dim.value - c) for c in candidates) > _LINEAR_TOL_MM:
                contradictions.append(Contradiction(
                    message=(f"Линейный размер {dim.raw_text!r} = {dim.value:g} мм "
                             f"не связан ни с габаритом, ни со ступенями детали"),
                    dimension_ids=[dim.id], severity="error"))
        # THREAD dimensions describe the threaded cylinder — matched against
        # features in Phase 2 (thread modelling out of scope), skipped for now.

    return scaled, contradictions
