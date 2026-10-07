import pytest
from shapely.geometry import Point

from dutch_waterways.network import NoRouteError

RD = 28992


def route(net, a, b, min_class=None):
    return net.route(Point(a), Point(b), min_class=min_class, crs=RD)


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
