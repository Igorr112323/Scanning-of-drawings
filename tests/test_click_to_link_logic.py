"""Click-to-link selection logic — headless, no GUI required.

The verification screen calls core.scan_linking.nearest_vector_element with
the clicked point (drawing mm coordinates) and confirm_dimension_link with the
picked element id. These tests cover exactly that decision path.
"""

from __future__ import annotations

from core.models import Dimension, ElementType, Symbol, VectorElement
from core.scan_linking import confirm_dimension_link, nearest_vector_element


def _line(id: str, x0: float, y0: float, x1: float, y1: float,
          type: ElementType = ElementType.CONTOUR) -> VectorElement:
    return VectorElement(id=id, type=type, points=[(x0, y0), (x1, y1)],
                         bbox=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))


def test_nearest_picks_closest_stroke():
    els = [_line("far", 0, 10, 100, 10),
           _line("near", 0, 2, 100, 2),
           _line("mid", 0, 5, 100, 5)]
    assert nearest_vector_element(els, 50, 4.0).id == "mid"
    assert nearest_vector_element(els, 50, 1.0).id == "near"


def test_nearest_respects_max_distance():
    els = [_line("l", 0, 10, 100, 10)]
    assert nearest_vector_element(els, 50, 8.0, max_dist=5.0).id == "l"
    assert nearest_vector_element(els, 50, 0.0, max_dist=5.0) is None


def test_nearest_vertical_and_endpoints():
    els = [_line("v", 30, 0, 30, 100)]
    assert nearest_vector_element(els, 34, 50).points[0][0] == 30
    # beyond the segment end: distance to the endpoint, still picked
    assert nearest_vector_element(els, 32, 104, max_dist=10.0).id == "v"
    assert nearest_vector_element(els, 32, 500, max_dist=10.0) is None


def test_text_elements_are_never_link_targets():
    text = VectorElement(id="t", type=ElementType.TEXT, points=[(50, 50)],
                         text="240", bbox=(40, 45, 60, 55))
    assert nearest_vector_element([text], 50, 50) is None


def test_nearest_prefers_horizontal_over_parallel_misses():
    els = [_line("top", 0, 20, 300, 20), _line("bottom", 0, 80, 300, 80)]
    assert nearest_vector_element(els, 150, 18.0).id == "top"
    assert nearest_vector_element(els, 150, 82.0).id == "bottom"


def test_confirm_dimension_link_flips_state():
    dim = Dimension(id="D1", symbol=Symbol.DIAMETER, value=60.0, raw_text="060",
                    confidence=0.8, linked_element_id=None, is_uncertain=True,
                    anchor=(473.0, 620.0))
    out = confirm_dimension_link(dim, "L-0028")
    assert out.is_uncertain is False
    assert out.confidence == 1.0
    assert out.linked_element_id == "L-0028"
    # value/symbol/anchor untouched; original object not mutated
    assert out.value == 60.0 and out.symbol is Symbol.DIAMETER
    assert out.anchor == dim.anchor
    assert dim.is_uncertain is True and dim.linked_element_id is None


def test_confirm_dimension_link_after_wrong_guess():
    dim = Dimension(id="D2", symbol=Symbol.LINEAR, value=240.0, raw_text="240",
                    confidence=0.95, linked_element_id="L-0071", is_uncertain=False,
                    anchor=(1102.0, 1330.0))
    out = confirm_dimension_link(dim, "L-0007")
    assert out.linked_element_id == "L-0007"
    assert out.is_uncertain is False
