import numpy as np
import pandas as pd
import pytest

from dutch_waterways.build import build_network, join_limits
from dutch_waterways.structures import build_structures, passable


@pytest.fixture
def structures(toy_layers, toy_structure_layers):
    bridges, openings, locks, chambers, _ = toy_structure_layers
    edges = build_network(*toy_layers)
    return build_structures(edges, bridges, openings, locks, chambers).set_index("structure_id")


def test_structures_grouped_with_passages(structures):
    assert sorted(structures.index) == [100, 101, 102, 200]  # ruined bridge 103 left out
    low, lift, unknown, lock = (structures.loc[i] for i in (100, 101, 102, 200))
    assert (low.kind, low["name"], low.section_id, low.movable) == ("bridge", "Low bridge", 1, False)
    assert list(low.passage_clearance) == [5.0]
    assert lift.movable
    assert list(lift.passage_width) == [12.0, 8.0]
    assert list(lift.passage_clearance) == [3.0, np.inf]
    assert len(unknown.passage_width) == 0
    assert (lock.kind, lock["name"], lock.section_id) == ("lock", "Toy lock", 3)
    assert list(lock.passage_length) == [100.0]
    assert list(lock.passage_width) == [8.0]  # the gate, narrower than the chamber


def test_structure_offsets_along_section(structures):
    assert structures.loc[100].offset_m == pytest.approx(500)
    assert structures.loc[101].offset_m == pytest.approx(500)
    assert structures.loc[200].offset_m == pytest.approx(500)


def test_passable_needs_one_passage_that_fits_all(structures):
    s = structures.loc[[100, 101, 102, 200]]
    assert passable(s).tolist() == [True] * 4
    assert passable(s, air_draught=6).tolist() == [False, True, True, True]
    # Lift bridge: 10 m beam fits only the low side span; 10 m air only the
    # lift span. The lock's 8 m gate is too narrow for 10 m.
    assert passable(s, beam=10, air_draught=10).tolist() == [False, False, True, False]
    assert passable(s, beam=7, air_draught=10).tolist() == [False, True, True, True]
    assert passable(s, length=120).tolist() == [True, True, True, False]


def test_passable_unknown_dimension_does_not_block():
    s = pd.DataFrame({"passage_width": [[np.nan]], "passage_length": [[np.inf]],
                      "passage_clearance": [[4.0]]})
    assert passable(s, beam=50).tolist() == [True]
    assert passable(s, air_draught=5).tolist() == [False]


def test_join_limits_takes_strictest():
    sections = pd.DataFrame({"routeid": [1, 1, 2], "routekmbegin": [0.0, 5.0, 0.0],
                             "routekmend": [5.0, 10.0, 1.0]})
    legal = pd.DataFrame({"routeid": [1, 1], "routekmbegin": [0.0, 4.0], "routekmend": [4.0, 10.0],
                          "generallength": [110.0, 80.0], "generaldepth": [3.0, 0.0]})
    visuris = pd.DataFrame({"routeid": [1], "routekmbegin": [0.0], "routekmend": [10.0],
                            "maxlength": [100.0], "maxwidth": [11.4]})
    out = join_limits(sections, max_dimensions=legal, visuris_dimensions=visuris)
    assert out.max_length.tolist()[:2] == [80.0, 80.0]  # section 0 overlaps both legal records
    assert out.max_beam.tolist()[:2] == [11.4, 11.4]
    assert out.max_draught.tolist()[0] == 3.0
    assert np.isnan(out.max_draught.tolist()[1])  # 0 means unknown
    assert out.iloc[2].isna().all()
