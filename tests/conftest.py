import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from dutch_waterways.build import CRS, STUB_KM


def fis_sections(rows):
    """A GeoDataFrame shaped like the FIS ``vaarwegvak`` layer.

    ``rows`` are (id, start, end, routeid, km_begin, km_end, coords).
    """
    records, geoms = [], []
    for sid, start, end, routeid, kb, ke, coords in rows:
        line = LineString(coords)
        stub = kb == ke
        records.append(
            dict(
                id=sid,
                startjunctionid=start,
                endjunctionid=end,
                name=f"section {sid}",
                routeid=routeid,
                fairwayid=routeid,
                routekmbegin=kb,
                routekmend=ke,
                length=STUB_KM if stub else line.length / 1000,
                foreigncode="DE00001" if stub else None,
                direction="H",
            )
        )
        geoms.append(line)
    return gpd.GeoDataFrame(records, geometry=geoms, crs=CRS)


def fis_junctions(positions):
    return gpd.GeoDataFrame(
        {"id": list(positions)},
        geometry=[Point(xy) for xy in positions.values()],
        crs=CRS,
    )


@pytest.fixture
def toy_layers():
    """A square of fairways in RD metres.

    1 ---- e1 (V_A) ---- 2 ---- e2 (II) ---- 3
    |                    |                   |
    e3 (V_A)         e5 (no class)       e4 (V_A)
    |                    |                   |
    4' ----------------- 4 ------------------'

    e3 runs 1 -> (0,1000) -> 4 and e4 runs 4 -> (2000,1000) -> 3, each 2000 m.
    Section 6 is a foreign stub from 3 far to the east.
    """
    junctions = {1: (0, 0), 2: (1000, 0), 3: (2000, 0), 4: (1000, 1000), 99: (900000, 0)}
    sections = fis_sections(
        [
            (1, 1, 2, 10, 0.0, 1.0, [(0, 0), (1000, 0)]),
            (2, 2, 3, 10, 1.0, 2.0, [(1000, 0), (2000, 0)]),
            (3, 1, 4, 20, 0.0, 2.0, [(0, 0), (0, 1000), (1000, 1000)]),
            (4, 4, 3, 20, 2.0, 4.0, [(1000, 1000), (2000, 1000), (2000, 0)]),
            (5, 2, 4, 30, 0.0, 1.0, [(1000, 0), (1000, 1000)]),
            (6, 3, 99, 40, 0.0, 0.0, [(2000, 0), (900000, 0)]),
        ]
    )
    classes = gpd.GeoDataFrame(
        {
            "routeid": [10, 10, 20],
            "routekmbegin": [0.0, 1.0, 0.0],
            "routekmend": [1.0, 2.0, 4.0],
            "code": ["V_A", "II", "V_A"],
        }
    )
    return sections, classes, fis_junctions(junctions)


@pytest.fixture
def toy_network(toy_layers):
    from dutch_waterways.build import build_network
    from dutch_waterways.network import Network

    return Network(build_network(*toy_layers))


@pytest.fixture
def toy_structure_layers():
    """FIS-shaped bridge, opening, lock, chamber and dimension records for the toy square.

    - a fixed bridge on e1 at x=500: one opening 10 m wide, 5 m clearance
    - a movable bridge on e2 at x=1500: a fixed side span 12 m wide, 3 m
      clearance, and a lift span 8 m wide that opens without a height limit
    - a lock on e3 at (0, 500): one chamber 100 m long, 8 m wide
    - a bridge on e4 with no opening records
    - a ruined bridge on e1, which is ignored
    - e2 (routeid 10, km 1-2) allows 2.0 m draught; e1 allows 90 m length
    """
    bridges = gpd.GeoDataFrame(
        {
            "id": [100, 101, 102, 103],
            "name": ["Low bridge", "Lift bridge", "Unknown bridge", "Old bridge"],
            "fairwaysectionid": [1, 2, 4, 1],
            "canopen": ["No", "Yes", "No", "No"],
            "condition": ["CONSTRUCTED"] * 3 + ["RUINED"],
        },
        geometry=[Point(500, 0), Point(1500, 0), Point(2000, 500), Point(800, 0)],
        crs=CRS,
    )
    openings = gpd.GeoDataFrame(
        {
            "parentid": [100, 101, 101, 103],
            "fairwaysectionid": [1, 2, 2, 1],
            "name": ["opening", "side span", "lift span", "old"],
            "type": ["VST", "VST", "OPH", "VST"],
            "width": [10.0, 12.0, 8.0, 5.0],
            "clearanceheightclosed": [5.0, 3.0, 1.0, 1.0],
            "clearanceheightopened": [None, None, None, None],
            "condition": ["CONSTRUCTED"] * 3 + ["RUINED"],
        },
        geometry=[Point(500, 0), Point(1500, 3), Point(1500, -3), Point(800, 0)],
        crs=CRS,
    )
    locks = gpd.GeoDataFrame(
        {"id": [200], "name": ["Toy lock"], "fairwaysectionid": [3], "condition": ["CONSTRUCTED"]},
        geometry=[Point(0, 500).buffer(5)],
        crs=CRS,
    )
    chambers = gpd.GeoDataFrame(
        {
            "parentid": [200],
            "fairwaysectionid": [3],
            "name": ["chamber"],
            "length": [100.0],
            "schutlengteeb": [100.0],
            "gatewidth": [8.0],
            "width": [9.0],
        },
        geometry=[Point(0, 500).buffer(4)],
        crs=CRS,
    )
    max_dimensions = pd.DataFrame(
        {
            "routeid": [10, 10],
            "routekmbegin": [1.0, 0.0],
            "routekmend": [2.0, 1.0],
            "generaldepth": [2.0, None],
            "generallength": [None, 90.0],
        }
    )
    return bridges, openings, locks, chambers, max_dimensions


@pytest.fixture
def toy_vessel_network(toy_layers, toy_structure_layers):
    from dutch_waterways.build import build_network
    from dutch_waterways.network import Network
    from dutch_waterways.structures import build_structures

    bridges, openings, locks, chambers, max_dimensions = toy_structure_layers
    edges = build_network(*toy_layers, max_dimensions=max_dimensions)
    return Network(edges, build_structures(edges, bridges, openings, locks, chambers))
