import pytest
from shapely.geometry import Point

from dutch_waterways.network import NoRouteError

RD = 28992


def route(net, a, b, min_class=None, **kwargs):
    return net.route(Point(a), Point(b), min_class=min_class, crs=RD, **kwargs)


def test_route_shortest_on_all_fairways(toy_network):
    r = route(toy_network, (0, -10), (2000, -10))
    assert r.length_m == pytest.approx(2000)
    assert r.access_m == pytest.approx(20)
    assert r.sections.section_id.tolist() == [1, 2]
    assert r.smallest_class == "II"


def test_route_class_filter_detours(toy_network):
    r = route(toy_network, (0, -10), (2000, -10), min_class="IV")
    assert r.length_m == pytest.approx(4000)
    assert r.sections.section_id.tolist() == [3, 4]
    assert r.smallest_class == "V_A"


def test_route_partial_sections_and_geometry(toy_network):
    r = route(toy_network, (250, 5), (1500, -5))
    assert r.length_m == pytest.approx(1250)
    assert r.geometry.length == pytest.approx(1250)
    assert r.geometry.coords[0] == pytest.approx((250, 0))
    assert r.geometry.coords[-1] == pytest.approx((1500, 0))


def test_route_against_geometry_direction(toy_network):
    r = route(toy_network, (1800, 1010), (1010, 400), min_class=None)
    # 4 -> 3 section, sailing backwards from x=1800 to junction 4, then down e5.
    assert r.length_m == pytest.approx(800 + 600)
    assert r.geometry.length == pytest.approx(r.length_m)
    assert r.geometry.coords[0] == pytest.approx((1800, 1000))
    assert r.geometry.coords[-1] == pytest.approx((1000, 400))


def test_route_within_one_section(toy_network):
    r = route(toy_network, (300, 0), (700, 0))
    assert r.length_m == pytest.approx(400)
    assert r.sections.section_id.tolist() == [1]
    assert r.geometry.length == pytest.approx(400)


def test_route_between_points_on_one_junction(toy_network):
    r = route(toy_network, (1000, -10), (1000, -20))
    assert r.length_m == 0
    assert r.sections.empty
    assert r.smallest_class is None


def test_route_never_uses_stubs(toy_network):
    r = route(toy_network, (5000, 0), (0, 0))
    assert 6 not in r.sections.section_id.tolist()
    assert r.origin.distance_m == pytest.approx(3000)  # snapped to junction 3


def test_unclassified_sections_excluded_by_class_filter(toy_network):
    sel = toy_network.select("_0")
    assert 5 not in sel.section_id.tolist()
    assert 5 in toy_network.select(None).section_id.tolist()


def test_no_route_for_too_large_class(toy_network):
    with pytest.raises(NoRouteError):
        route(toy_network, (0, 0), (2000, 0), min_class="VI_A")


def test_route_from_lon_lat(toy_network):
    import geopandas as gpd

    a, b = gpd.GeoSeries([Point(0, -10), Point(2000, -10)], crs=RD).to_crs(4326)
    r = toy_network.route((a.x, a.y), (b.x, b.y))
    assert r.length_m == pytest.approx(2000, abs=1)


def test_access_snap_vs_network(toy_network):
    # Start on e5 (no class). Snapping for class IV jumps to the nearest class
    # IV section; network access sails e5 and reports it as below class.
    snap = route(toy_network, (1010, 500), (0, 1000), min_class="IV")
    assert snap.origin.edge != 4  # row label of e5
    assert snap.below_class_m == 0

    net = route(toy_network, (1010, 500), (0, 1000), min_class="IV", access="network")
    assert net.origin.distance_m == pytest.approx(10)
    assert net.sections.section_id.tolist() == [5, 3]
    assert net.length_m == pytest.approx(500 + 1000)
    assert net.below_class_m == pytest.approx(500)
    assert net.smallest_class == "V_A"  # e5 has no known class


def test_access_network_prefers_usable_fairways(toy_network):
    # From junction 2 to junction 4: e5 is 1000 m but below class; the class
    # IV detour 2-1-4 is 3000 m and wins.
    r = route(toy_network, (1000, -1), (1000, 1001), min_class="IV", access="network")
    assert r.below_class_m == 0
    assert r.length_m == pytest.approx(3000)


def test_max_access_raises(toy_network):
    from dutch_waterways import TooFarError

    with pytest.raises(TooFarError):
        toy_network.route(Point(0, -5000), Point(2000, 0), crs=RD, max_access_m=1000)
    r = toy_network.route(Point(0, -500), Point(2000, 0), crs=RD, max_access_m=1000)
    assert r.origin.distance_m == pytest.approx(500)


def test_bad_access_mode(toy_network):
    with pytest.raises(ValueError):
        toy_network.route(Point(0, 0), Point(1, 0), crs=RD, access="fly")


def test_od_matrix_matches_route(toy_network):
    pts = {"a": Point(0, -10), "b": Point(2000, -10), "c": Point(1000, 990), "d": Point(300, 0)}
    m = toy_network.od_matrix(pts, crs=RD)
    assert list(m.index) == list(m.columns) == ["a", "b", "c", "d"]
    assert (m.values.diagonal() == 0).all()
    assert (m.values == m.values.T).all()
    for i in pts:
        for j in pts:
            r = toy_network.route(pts[i], pts[j], crs=RD)
            assert m.loc[i, j] == pytest.approx(r.length_m / 1000)
    assert m.attrs["access_km"]["a"] == pytest.approx(0.01)


def test_od_matrix_several_points_on_one_section(toy_network):
    pts = [Point(100, 0), Point(900, 0), Point(500, 0)]
    m = toy_network.od_matrix(pts, crs=RD)
    assert m.iloc[0, 1] == pytest.approx(0.8)
    assert m.iloc[0, 2] == pytest.approx(0.4)
    assert m.iloc[2, 1] == pytest.approx(0.4)


def test_od_matrix_network_access_reports_below_class(toy_network):
    pts = {"e5": Point(1000, 500), "west": Point(0, 1000)}
    m = toy_network.od_matrix(pts, min_class="IV", access="network", crs=RD)
    assert m.loc["e5", "west"] == pytest.approx(1.5)
    assert m.attrs["below_class_km"].loc["e5", "west"] == pytest.approx(0.5)


def test_od_matrix_unreachable_is_nan(toy_layers):
    from dutch_waterways.build import build_network
    from dutch_waterways.network import Network

    from .conftest import fis_sections

    sections, classes, junctions = toy_layers
    island = fis_sections([(7, 50, 51, 70, 0.0, 1.0, [(0, 5000), (1000, 5000)])])
    import pandas as pd

    net = Network(build_network(pd.concat([sections, island], ignore_index=True), classes))
    m = net.od_matrix([Point(0, 0), Point(500, 5000)], crs=RD)
    assert m.isna().values.sum() == 2


# --- vessel dimensions, bridges and locks --------------------------------

def vroute(net, a, b, **kwargs):
    return net.route(Point(a), Point(b), crs=RD, **kwargs)


def test_route_lists_structures_in_order(toy_vessel_network):
    r = vroute(toy_vessel_network, (0, -10), (2000, -10))
    assert r.structures.name.tolist() == ["Low bridge", "Lift bridge"]
    assert r.structures.at_km.tolist() == pytest.approx([0.5, 1.5])
    back = vroute(toy_vessel_network, (2000, -10), (0, -10))
    assert back.structures.name.tolist() == ["Lift bridge", "Low bridge"]
    assert back.structures.at_km.tolist() == pytest.approx([0.5, 1.5])


def test_route_skips_structures_behind_the_origin(toy_vessel_network):
    r = vroute(toy_vessel_network, (700, 0), (2000, 0))
    assert r.structures.name.tolist() == ["Lift bridge"]
    assert r.structures.at_km.tolist() == pytest.approx([0.8])


def test_air_draught_avoids_low_bridge(toy_vessel_network):
    from dutch_waterways import Vessel

    r = vroute(toy_vessel_network, (0, -10), (2000, -10), vessel=Vessel(air_draught=6))
    assert r.sections.section_id.tolist() == [3, 4]
    assert r.length_m == pytest.approx(4000)
    assert r.locks.name.tolist() == ["Toy lock"]
    assert r.summary()["locks"] == 1


def test_length_blocked_by_lock_and_section_limit(toy_vessel_network):
    from dutch_waterways import Vessel

    # 95 m is too long for e1 (90 m) but fits the lock: goes round by e3.
    r = vroute(toy_vessel_network, (0, -10), (2000, -10), vessel=Vessel(length=95))
    assert 1 not in r.sections.section_id.tolist()
    # 120 m fits neither e1 nor the lock on e3; e5 and e2 are still open.
    r = vroute(toy_vessel_network, (1000, -10), (2000, -10), vessel=Vessel(length=120))
    assert r.sections.section_id.tolist() == [2]
    # Add 2.5 m draught and only e5 and e4 remain: the origin snaps 1 km away.
    r = vroute(toy_vessel_network, (0, -10), (2000, 500), vessel=Vessel(length=120, draught=2.5))
    assert r.origin.distance_m == pytest.approx(1000, abs=1)
    assert r.sections.section_id.tolist() == [5, 4]


def test_draught_limit(toy_vessel_network):
    from dutch_waterways import Vessel

    r = vroute(toy_vessel_network, (0, -10), (2000, -10), vessel=Vessel(draught=2.5))
    assert 2 not in r.sections.section_id.tolist()


def test_route_limits(toy_vessel_network):
    r = vroute(toy_vessel_network, (0, -10), (2000, -10))
    assert r.limits() == {"length": 90.0, "beam": 10.0, "draught": 2.0, "air_draught": 5.0}
    r = vroute(toy_vessel_network, (0, 400), (0, 600))
    assert r.limits() == {"length": 100.0, "beam": 8.0, "draught": None, "air_draught": None}


def test_vessel_class_and_min_class(toy_vessel_network):
    from dutch_waterways import Vessel

    assert Vessel("Va").cemt == "V_A"
    r = vroute(toy_vessel_network, (0, -10), (2000, -10), vessel=Vessel("II"), min_class="IV")
    assert r.min_class == "IV"
    assert r.sections.section_id.tolist() == [3, 4]


def test_network_without_structures_has_none(toy_network):
    r = route(toy_network, (0, -10), (2000, -10))
    assert r.structures is None
    assert r.locks.empty and r.summary()["bridges"] == 0
