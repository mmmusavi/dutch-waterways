import json

import pytest
from shapely.geometry import Point

from dutch_waterways import places


class FakeNominatim:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def get(self, url, params, headers, timeout):
        self.calls.append(params)
        hits = self.hits

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return hits

        return R()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DUTCH_WATERWAYS_CACHE", str(tmp_path))
    monkeypatch.setattr(places, "_memory", {})
    monkeypatch.setattr(places, "MIN_INTERVAL_S", 0)


def test_geocode_and_cache(tmp_path):
    fake = FakeNominatim([{"lon": "5.07", "lat": "52.49"}])
    assert places.geocode("Volendam", session=fake) == (5.07, 52.49)
    assert fake.calls[0]["countrycodes"] == "nl"
    # Same name, different spacing and case: served from memory.
    assert places.geocode("  volendam ", session=fake) == (5.07, 52.49)
    assert len(fake.calls) == 1
    # A new process: served from disk.
    places._memory.clear()
    assert places.geocode("Volendam", session=fake) == (5.07, 52.49)
    assert len(fake.calls) == 1
    assert json.loads((tmp_path / "geocode.json").read_text()) == {"nl|volendam": [5.07, 52.49]}


def test_geocode_without_country():
    fake = FakeNominatim([{"lon": "6.0", "lat": "51.0"}])
    places.geocode("Duisburg", country=None, session=fake)
    assert "countrycodes" not in fake.calls[0]


def test_geocode_not_found():
    with pytest.raises(LookupError):
        places.geocode("Nowhere at all", session=FakeNominatim([]))


def test_resolve_kinds(monkeypatch):
    monkeypatch.setattr(places, "geocode", lambda name: (5.387, 52.161))
    label, pt = places.resolve("Amersfoort")
    assert label == "Amersfoort"
    assert pt.x == pytest.approx(155_000, abs=1_000) and pt.y == pytest.approx(463_000, abs=1_000)

    assert places.resolve((5.387, 52.161))[1].equals_exact(pt, 1e-6)
    label, rd = places.resolve(Point(155000, 463000), crs=28992)
    assert label is None and rd == Point(155000, 463000)
