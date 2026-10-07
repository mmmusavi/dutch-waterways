import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString

from dutch_waterways.build import (
    COLUMNS,
    build_from_dir,
    build_network,
    join_classes,
    summarize,
)

from .conftest import fis_junctions, fis_sections


def classes(rows):
    return pd.DataFrame(rows, columns=["routeid", "routekmbegin", "routekmend", "code"])


def sections_km(rows):
    """Sections with only the fields join_classes reads: (routeid, km_begin, km_end)."""
    return pd.DataFrame(rows, columns=["routeid", "routekmbegin", "routekmend"])


def test_join_takes_largest_overlap():
    sec = sections_km([(1, 0.0, 10.0)])
    cls = classes([(1, 0.0, 3.0, "V_A"), (1, 3.0, 20.0, "II")])
    assert join_classes(sec, cls).tolist() == ["II"]


def test_join_tie_takes_smaller_class():
    sec = sections_km([(1, 0.0, 10.0)])
    cls = classes([(1, 0.0, 5.0, "V_A"), (1, 5.0, 10.0, "III")])
    assert join_classes(sec, cls).tolist() == ["III"]


def test_join_ignores_touching_records_and_other_routes():
    sec = sections_km([(1, 5.0, 10.0)])
    cls = classes([(1, 0.0, 5.0, "V_A"), (1, 10.0, 15.0, "V_A"), (2, 5.0, 10.0, "V_A")])
    assert join_classes(sec, cls).tolist() == [None]


def test_join_handles_point_sections_and_reversed_km():
    sec = sections_km([(1, 4.0, 4.0), (1, 9.0, 6.0)])
    cls = classes([(1, 0.0, 5.0, "IV"), (1, 10.0, 5.0, "Vb")])
    assert join_classes(sec, cls).tolist() == ["IV", "V_B"]


def test_join_keeps_index():
    sec = sections_km([(1, 0.0, 1.0), (9, 0.0, 1.0), (1, 1.0, 2.0)]).set_axis([7, 3, 5])
    cls = classes([(1, 0.0, 2.0, "I")])
    out = join_classes(sec, cls)
    assert out.to_dict() == {7: "I", 3: None, 5: "I"}


def test_build_network_columns_and_classes(toy_layers):
    edges = build_network(*toy_layers)
    assert list(edges.columns) == COLUMNS
    assert edges.crs.to_epsg() == 28992
    assert edges.set_index("section_id").cemt.to_dict() == {
        1: "V_A", 2: "II", 3: "V_A", 4: "V_A", 5: None, 6: None
    }
    assert edges.is_stub.tolist() == [False] * 5 + [True]
    assert edges.length_m.iloc[2] == pytest.approx(2000)


def test_build_network_orients_geometry_from_source_to_target(toy_layers):
    sections, cls, junctions = toy_layers
    sections = sections.copy()
    sections.loc[0, "geometry"] = LineString([(1000, 0), (0, 0)])  # stored backwards
    edges = build_network(sections, cls, junctions)
    assert list(edges.geometry.iloc[0].coords) == [(0, 0), (1000, 0)]


def test_build_network_merges_contiguous_multilines():
    sections = fis_sections([(1, 1, 2, 10, 0.0, 2.0, [(0, 0), (2000, 0)])])
    sections.loc[0, "geometry"] = MultiLineString([[(0, 0), (1000, 0)], [(1000, 0), (2000, 0)]])
    edges = build_network(sections, classes([]), fis_junctions({1: (0, 0), 2: (2000, 0)}))
    assert edges.geometry.iloc[0].geom_type == "LineString"


def test_summarize(toy_layers):
    s = summarize(build_network(*toy_layers))
    assert s["routable_sections"] == 5
    assert s["stub_sections"] == 1
    assert s["classified_sections"] == 4
    assert s["routable_km"] == pytest.approx(7.0)
    assert s["km_by_class"] == {"II": 1.0, "V_A": 5.0}


def test_build_from_dir_writes_parquet_and_metadata(tmp_path, toy_layers):
    sections, cls, junctions = toy_layers
    raw = tmp_path / "raw"
    raw.mkdir()
    sections.to_crs(4326).to_file(raw / "sections.geojson", driver="GeoJSON")
    gpd.GeoDataFrame(cls, geometry=[None] * len(cls), crs=4326).to_file(
        raw / "classes.geojson", driver="GeoJSON"
    )
    junctions.to_crs(4326).to_file(raw / "junctions.geojson", driver="GeoJSON")

    out = tmp_path / "network.parquet"
    meta = build_from_dir(raw, out)
    edges = gpd.read_parquet(out)
    assert len(edges) == 6
    assert edges.crs.to_epsg() == 28992
    assert json.loads(out.with_suffix(".json").read_text()) == meta
    assert meta["classified_sections"] == 4
