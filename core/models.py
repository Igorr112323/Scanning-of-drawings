"""Core data models for the DrawToSTEP pipeline.

These dataclasses are the contract between pipeline stages:

    parse_pdf / preprocess_scan+vectorize  ->  Drawing
    recognize_dimensions(drawing)           ->  list[Dimension]
    solve_constraints(dimensions, profile)  ->  (list[ProfilePoint], list[Contradiction])
    build_solid(profile, dimensions)        ->  cadquery.Workplane (compound/solid)

Rule of the house (never broken): the app must not invent a dimension.
Any dimension with confidence < 0.85 or one that cannot be linked to a
drawing element is marked ``is_uncertain=True`` and MUST be confirmed or
edited by the user before a solid is built.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

#: Confidence threshold below which a dimension is considered uncertain.
CONFIDENCE_THRESHOLD = 0.85


class ElementType(str, enum.Enum):
    """Classification of a vector element found on the drawing."""

    CONTOUR = "CONTOUR"
    DIMENSION_LINE = "DIMENSION_LINE"
    AXIS = "AXIS"
    HATCH = "HATCH"
    TEXT = "TEXT"
    UNKNOWN = "UNKNOWN"


class Symbol(str, enum.Enum):
    """Dimension symbol as printed on a GOST / ESKD drawing."""

    DIAMETER = "DIAMETER"      # Ø
    RADIUS = "RADIUS"          # R
    LINEAR = "LINEAR"          # plain number (length / height / width)
    THREAD = "THREAD"          # M (metrical thread)
    CHAMFER = "CHAMFER"        # "2×45°", "C2" — leg length in mm
    UNKNOWN = "UNKNOWN"


@dataclass
class VectorElement:
    """A single classified vector element (line segment, circle, polyline, text)."""

    id: str
    type: ElementType
    points: list[tuple[float, float]] = field(default_factory=list)
    # stroke width in PDF points (1 mm ≈ 2.835 pt); used for contour vs thin lines
    stroke_width: float = 0.0
    # dash pattern, e.g. "[8 3 2 3] 0" for a GOST dash-dot axis line; None/empty = solid
    dash: Optional[str] = None
    text: Optional[str] = None          # only for TEXT elements
    bbox: Optional[tuple[float, float, float, float]] = None  # (x0, y0, x1, y1)
    ocr_confidence: Optional[float] = None  # OCR confidence, raster scans only
    arrow_end: bool = False                 # filled triangle at a stroke end (scan linking signal)


@dataclass
class Dimension:
    """A dimension recognized on the drawing.

    ``is_uncertain`` is True whenever confidence < CONFIDENCE_THRESHOLD or the
    dimension could not be linked to a drawing element — the UI must highlight
    those in yellow and block 3D generation until the user confirms them.
    """

    id: str
    symbol: Symbol
    value: float                       # in millimetres
    raw_text: str                      # original text as printed, e.g. "Ø50"
    confidence: float
    linked_element_id: Optional[str]
    is_uncertain: bool
    anchor: Optional[tuple[float, float]] = None  # position of the text on the sheet
    # Set by core.diameter_recovery when RapidOCR dropped the Ø glyph but the
    # printed value matches the geometry-measured diameter: the user still
    # confirms (one click), but no re-typing / click-to-link is needed.
    proposed_by_geometry: bool = False

    def label(self) -> str:
        prefix = {
            Symbol.DIAMETER: "Ø",
            Symbol.RADIUS: "R",
            Symbol.THREAD: "M",
            Symbol.LINEAR: "",
            Symbol.CHAMFER: "",
            Symbol.UNKNOWN: "?",
        }[self.symbol]
        value = int(self.value) if float(self.value).is_integer() else self.value
        if self.symbol is Symbol.CHAMFER:
            return f"{value}×45°"
        return f"{prefix}{value}"


@dataclass
class ProfilePoint:
    """Point of the half-profile in (x, r) millimetres, revolved around the X axis."""

    x: float
    r: float


@dataclass
class UncertainDimension:
    """A dimension flagged by the pipeline that the user must resolve."""

    dimension: Dimension
    reason: str


@dataclass
class Contradiction:
    """A consistency problem found by the constraint solver."""

    message: str
    dimension_ids: list[str] = field(default_factory=list)
    severity: str = "error"            # "error" | "warning"


@dataclass
class View:
    """One view projected on the sheet (v1: a single main view)."""

    name: str
    bbox: tuple[float, float, float, float]
    elements: list[VectorElement] = field(default_factory=list)
    axis_y: Optional[float] = None     # Y of the axis line in sheet coordinates


@dataclass
class Drawing:
    """Parsed drawing: the root object passed between pipeline stages."""

    source_path: str
    page_width: float
    page_height: float
    elements: list[VectorElement] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    # Half-profile of a body of revolution, derived from CONTOUR elements and
    # the axis line. Coordinates in millimetres, r measured from the axis.
    profile: list[ProfilePoint] = field(default_factory=list)
    # Centre through-hole diameter in mm, detected from inner-wall contour
    # lines (bored parts in section views). None when the part is solid.
    bore_diameter: Optional[float] = None

    def elements_of_type(self, element_type: ElementType) -> list[VectorElement]:
        return [e for e in self.elements if e.type == element_type]

    def contour_elements(self) -> list[VectorElement]:
        return self.elements_of_type(ElementType.CONTOUR)

    def axis_elements(self) -> list[VectorElement]:
        return self.elements_of_type(ElementType.AXIS)
