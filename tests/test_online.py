"""End-to-end against the live FIS service. Run with ``pytest -m online``."""

import pytest

from dutch_waterways import fis
from dutch_waterways.build import build_from_dir
from dutch_waterways.network import Network

pytestmark = pytest.mark.online

VOLENDAM = (5.0710, 52.4950)
AMERSFOORT = (5.3870, 52.1610)
BBOX = (4.90, 52.05, 5.65, 52.60)


@pytest.fixture(scope="module")
def network(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fis")
    fis.download(tmp / "raw", bbox=BBOX)
    build_from_dir(tmp / "raw", tmp / "network.parquet")
    return Network.load(tmp / "network.parquet")


def test_volendam_amersfoort_commercial(network):
    # Prototype result (2026-10-07): Markermeer, IJmeer, Gooimeer, Eemmeer, Eem.
    r = network.route(VOLENDAM, AMERSFOORT, min_class="I")
    assert r.length_m / 1000 == pytest.approx(73.0, abs=1.0)
    assert r.smallest_class == "II"


def test_volendam_amersfoort_all_fairways_is_shorter(network):
    r = network.route(VOLENDAM, AMERSFOORT)
    assert r.length_m / 1000 == pytest.approx(66.4, abs=1.0)


def test_place_names_and_od_matrix(network):
    m = network.od_matrix(["Volendam", "Amersfoort"], min_class="I")
    assert m.loc["Volendam", "Amersfoort"] == pytest.approx(73.0, abs=2.0)


def test_class_iv_network_access(network):
    # The Eem is below class IV: network access sails it and says how much.
    r = network.route(VOLENDAM, AMERSFOORT, min_class="IV", access="network")
    assert r.access_m < 1000
    assert r.below_class_m > 10_000


def test_bridges_on_route_and_air_draught(network):
    from dutch_waterways import NoRouteError, Vessel

    r = network.route(VOLENDAM, AMERSFOORT, min_class="I")
    assert "Hollandse Brug" in set(r.bridges.name)
    # The Eem into Amersfoort has fixed bridges of about 7.2 m.
    with pytest.raises(NoRouteError):
        network.route(VOLENDAM, AMERSFOORT, vessel=Vessel("I", air_draught=8))
