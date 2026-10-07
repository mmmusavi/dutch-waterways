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
