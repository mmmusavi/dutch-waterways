import csv
import io

import geopandas as gpd
import pytest
from shapely.geometry import Point

from dutch_waterways import cli, data
from dutch_waterways.build import build_network


def lonlat(x, y):
    p = gpd.GeoSeries([Point(x, y)], crs=28992).to_crs(4326).iloc[0]
    return f"{p.x:.7f},{p.y:.7f}"


@pytest.fixture
def toy_parquet(tmp_path, toy_layers):
    path = tmp_path / "network.parquet"
    build_network(*toy_layers).to_parquet(path)
    return path


def test_cli_route(toy_parquet, tmp_path, capsys):
    out = tmp_path / "route.geojson"
    html = tmp_path / "route.html"
    cli.main(["route", lonlat(0, -10), lonlat(2000, -10), "--network", str(toy_parquet),
              "--class", "IV", "--geojson", str(out), "--map", str(html)])
    text = capsys.readouterr().out
    assert "4.0 km" in text and "smallest class:  V_A" in text
    assert gpd.read_file(out).iloc[0].smallest_class == "V_A"
    assert "leaflet" in html.read_text().lower()


def test_cli_route_too_far_exits(toy_parquet):
    with pytest.raises(SystemExit, match="no route"):
        cli.main(["route", lonlat(0, -5000), lonlat(2000, 0), "--network", str(toy_parquet),
                  "--max-access", "100"])


def test_cli_od_from_file(toy_parquet, tmp_path, capsys):
    f = tmp_path / "places.csv"
    a, b = lonlat(0, -10).split(","), lonlat(2000, -10).split(",")
    f.write_text(f"name,lon,lat\nwest,{a[0]},{a[1]}\neast,{b[0]},{b[1]}\n")
    cli.main(["od", "--file", str(f), "--network", str(toy_parquet)])
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == ["", "west", "east"]
    assert rows[1] == ["west", "0.0", "2.0"]


def test_place_parsing():
    assert cli._place("5.07,52.49") == (5.07, 52.49)
    assert cli._place(" -1.5 , 52 ") == (-1.5, 52.0)
    assert cli._place("Den Helder") == "Den Helder"


def test_default_network_uses_cache(toy_parquet, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "network.parquet").write_bytes(toy_parquet.read_bytes())
    monkeypatch.setenv("DUTCH_WATERWAYS_CACHE", str(cache))
    monkeypatch.setattr(data, "_default", None)
    monkeypatch.setattr(data, "ensure_network", lambda refresh=False: data.network_path())
    import dutch_waterways as dw

    r = dw.route(Point(0, -10), Point(2000, -10), crs=28992)
    assert r.length_m == pytest.approx(2000)


def test_route_map_layers(toy_network):
    folium = pytest.importorskip("folium")
    r = toy_network.route(Point(1010, 500), Point(0, 1100), min_class="IV", access="network", crs=28992)
    m = r.to_map()
    lines = [c for c in m._children.values() if isinstance(c, folium.PolyLine)]
    colours = {line.options["color"] for line in lines}
    assert {"#1f6feb", "#d97706", "#6b7280"} <= colours


@pytest.fixture
def toy_vessel_parquet(tmp_path, toy_vessel_network):
    from dutch_waterways.build import structures_path

    path = tmp_path / "vessel.parquet"
    toy_vessel_network.edges.to_parquet(path)
    toy_vessel_network.structures.to_parquet(structures_path(path))
    return path


def test_cli_route_with_vessel(toy_vessel_parquet, capsys):
    cli.main(["route", lonlat(0, -10), lonlat(2000, -10), "--network", str(toy_vessel_parquet),
              "--air-draught", "6"])
    text = capsys.readouterr().out
    assert "4.0 km" in text
    assert "locks:           1" in text and "Toy lock" in text
    assert "route allows:    length 100 m, beam 8 m" in text


def test_route_map_marks_structures(toy_vessel_network):
    folium = pytest.importorskip("folium")
    r = toy_vessel_network.route(Point(0, -10), Point(2000, -10), crs=28992)
    m = r.to_map()
    markers = [c for c in m._children.values() if isinstance(c, folium.CircleMarker)]
    assert len(markers) == 2
    assert "Low bridge (fixed bridge)" in m.get_root().render()


def test_old_cached_build_is_rebuilt(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("DUTCH_WATERWAYS_CACHE", str(tmp_path))
    data.network_path().write_bytes(b"old")
    data.network_path().with_suffix(".json").write_text(json.dumps({"built": "2026-10-07"}))
    calls = []
    monkeypatch.setattr("dutch_waterways.fis.download", lambda d: calls.append("download"))
    monkeypatch.setattr("dutch_waterways.build.build_from_dir", lambda r, o: calls.append("build"))
    data.ensure_network()
    assert calls == ["download", "build"]


def test_dimensions_without_structures_warn(toy_network):
    from dutch_waterways import Vessel

    with pytest.warns(UserWarning, match="not checked"):
        toy_network.route(Point(0, -10), Point(2000, -10), crs=28992, vessel=Vessel(beam=5))
