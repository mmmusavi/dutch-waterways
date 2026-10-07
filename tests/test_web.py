"""The browser router (web/router.js) gives the same answers as the Python one."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from shapely.geometry import Point

from dutch_waterways import NoRouteError, TooFarError, Vessel
from dutch_waterways.web import to_json

ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "tests" / "js" / "run_routes.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

JS_DIMS = {"length": "length", "beam": "beam", "draught": "draught", "air_draught": "airDraught"}


def run_js(network_json: dict, cases: list[dict], tmp_path) -> list[dict]:
    net = tmp_path / "network.json"
    net.write_text(json.dumps(network_json))
    cs = tmp_path / "cases.json"
    cs.write_text(json.dumps(cases))
    out = subprocess.run(["node", str(RUNNER), str(net), str(cs)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def js_case(a, b, vessel=None, access="snap", max_access=None):
    v = {}
    if vessel is not None:
        v["cemt"] = vessel.cemt
        v.update({JS_DIMS[k]: getattr(vessel, k) for k in JS_DIMS if getattr(vessel, k) is not None})
    return {"a": list(a), "b": list(b), "vessel": v, "access": access, "maxAccess": max_access}


def compare(network, cases, tmp_path, rel=1e-6):
    js = run_js(to_json(network, simplify_m=0), [js_case(*c) for c in cases], tmp_path)
    for case, got in zip(cases, js):
        a, b, vessel, access, max_access = case
        try:
            r = network.route(Point(a), Point(b), vessel=vessel, access=access,
                              max_access_m=max_access, crs=28992)
        except TooFarError:
            assert got == {"error": "TooFarError"}, case
            continue
        except NoRouteError:
            assert got == {"error": "NoRouteError"}, case
            continue
        assert "error" not in got, (case, got)
        assert got["lengthM"] == pytest.approx(r.length_m, rel=rel, abs=0.5), case
        assert got["belowClassM"] == pytest.approx(r.below_class_m, rel=rel, abs=0.5), case
        assert got["accessM"] == pytest.approx(r.access_m, abs=0.5), case
        assert got["smallestClass"] == r.smallest_class, case
        assert got["sections"] == r.sections.section_id.tolist(), case
        names = [] if r.structures is None else r.structures.name.tolist()
        assert got["structures"] == names, case
        if r.structures is not None:
            assert got["atKm"] == pytest.approx(r.structures.at_km.tolist(), abs=0.001), case
            expected = {JS_DIMS[k]: v for k, v in r.limits().items()}
            assert got["limits"] == expected, case
        assert got["start"] == pytest.approx(list(r.geometry.coords[0]), abs=0.5), case
        assert got["end"] == pytest.approx(list(r.geometry.coords[-1]), abs=0.5), case


def test_toy_network_matches_python(toy_network, tmp_path):
    cases = [
        ((0, -10), (2000, -10), None, "snap", None),
        ((0, -10), (2000, -10), Vessel("IV"), "snap", None),
        ((250, 5), (1500, -5), None, "snap", None),
        ((1800, 1010), (1010, 400), None, "snap", None),
        ((300, 0), (700, 0), None, "snap", None),
        ((1000, -10), (1000, -20), None, "snap", None),
        ((1010, 500), (0, 1000), Vessel("IV"), "network", None),
        ((1000, -1), (1000, 1001), Vessel("IV"), "network", None),
        ((0, 0), (2000, 0), Vessel("VI_A"), "snap", None),
        ((0, -5000), (2000, 0), None, "snap", 1000),
    ]
    compare(toy_network, cases, tmp_path)


def test_toy_vessels_match_python(toy_vessel_network, tmp_path):
    cases = [
        ((0, -10), (2000, -10), None, "snap", None),
        ((2000, -10), (0, -10), None, "snap", None),
        ((700, 0), (2000, 0), None, "snap", None),
        ((0, -10), (2010, 500), Vessel(air_draught=6), "snap", None),  # no tie
        ((0, -10), (2010, 500), Vessel(length=95), "snap", None),
        ((1000, -10), (2000, -10), Vessel(length=120), "snap", None),
        ((0, -10), (2000, 500), Vessel(length=120, draught=2.5), "snap", None),
        ((300, -10), (2010, 500), Vessel(draught=2.5), "snap", None),
        ((0, -10), (2000, -10), Vessel(beam=10, air_draught=10), "snap", None),
        ((0, 400), (0, 600), None, "snap", None),
    ]
    compare(toy_vessel_network, cases, tmp_path)


def test_export_shape(toy_vessel_network):
    data = to_json(toy_vessel_network)
    e = data["edges"]
    assert data["nodes"] == 4  # the stub's far junction is not routable
    assert len(e["source"]) == len(e["coords"]) == 5
    assert e["cemt"][4] == -1  # e5 has no class
    assert e["maxDraught"][1] == 2.0
    s = data["structures"]
    assert sorted(s["name"]) == ["Lift bridge", "Low bridge", "Toy lock", "Unknown bridge"]
    lift = s["passages"][s["name"].index("Lift bridge")]
    assert lift == [[12.0, None, 3.0], [8.0, None, None]]
    json.dumps(data, allow_nan=False)  # valid JSON: no NaN or Infinity
