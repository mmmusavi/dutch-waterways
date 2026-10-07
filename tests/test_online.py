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
