"""Turn raw FIS layers into a clean, routable network table.

The output is one row per fairway section (``vaarwegvak``) with its two end
junctions, its length, its CEMT class and its geometry in EPSG:28992 (RD New,
metres). Geometry always runs from ``source`` to ``target``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from . import cemt
from .fis import BASE_URL, LAYERS

CRS = 28992

# FIS models links into foreign networks as zero-km sections whose geometry is
# a straight placeholder line, sometimes hundreds of km long. They are kept in
# the table for reference but are not routable.
STUB_KM = 0.103

COLUMNS = [
    "section_id",
    "source",
    "target",
    "name",
    "routeid",
    "fairwayid",
    "km_begin",
    "km_end",
    "fis_km",
    "length_m",
    "cemt",
    "cemt_rank",
    "is_stub",
    "foreigncode",
    "geometry",
]


def read_layer(path: str | Path) -> gpd.GeoDataFrame:
    """Read a downloaded FIS GeoJSON layer and project it to RD New."""
    return gpd.read_file(path).to_crs(CRS)


def join_classes(sections: pd.DataFrame, classes: pd.DataFrame) -> pd.Series:
    """Return the CEMT code of each section (``None`` where unknown).

    A section takes the class of the class record on the same ``routeid``
    whose km range overlaps it most. Sections with an empty km range take the
    record that contains their km point. On equal overlap the smaller class
    wins, to stay on the safe side.
    """
    cls = pd.DataFrame(
        {
            "routeid": classes["routeid"].to_numpy(),
            "c_lo": np.minimum(classes["routekmbegin"], classes["routekmend"]),
            "c_hi": np.maximum(classes["routekmbegin"], classes["routekmend"]),
            "code": classes["code"].map(cemt.normalize),
        }
    )
    sec = pd.DataFrame(
        {
            "row": np.arange(len(sections)),
            "routeid": sections["routeid"].to_numpy(),
            "s_lo": np.minimum(sections["routekmbegin"], sections["routekmend"]),
            "s_hi": np.maximum(sections["routekmbegin"], sections["routekmend"]),
        }
    )
    m = sec.merge(cls, on="routeid")
    m["overlap"] = np.minimum(m.s_hi, m.c_hi) - np.maximum(m.s_lo, m.c_lo)
    point = m.s_hi == m.s_lo
    hit = np.where(point, (m.c_lo <= m.s_lo) & (m.s_lo <= m.c_hi), m.overlap > 1e-9)
    m = m[hit].assign(rank=lambda d: d.code.map(cemt.RANK))
    best = m.sort_values(["row", "overlap", "rank"], ascending=[True, False, True])
    best = best.drop_duplicates("row").set_index("row")["code"]

    out = pd.Series([None] * len(sections), index=sections.index, dtype=object)
    out.iloc[best.index.to_numpy()] = best.to_numpy()
    return out


def _single_line(geom):
    """Merge a MultiLineString into one LineString where it is contiguous."""
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        return merged if isinstance(merged, LineString) else geom
    return geom


def _orient(edges: gpd.GeoDataFrame, junctions: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Reverse geometries that run from ``target`` to ``source``."""
    pos = junctions.drop_duplicates("id").set_index("id").geometry
    geoms = edges.geometry.copy()
    for i, (g, s, t) in enumerate(zip(edges.geometry, edges.source, edges.target)):
        if not isinstance(g, LineString) or s not in pos.index or t not in pos.index:
            continue
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        forward = a.distance(pos[s]) + b.distance(pos[t])
        backward = a.distance(pos[t]) + b.distance(pos[s])
        if backward < forward:
            geoms.iloc[i] = g.reverse()
    return geoms


def build_network(
    sections: gpd.GeoDataFrame,
    classes: pd.DataFrame,
    junctions: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Build the network table from FIS sections, classes and junctions.

    Inputs are FIS layers as read by :func:`read_layer`. ``junctions`` is used
    to orient each geometry from ``source`` to ``target``; without it the FIS
    orientation is kept as is.
    """
    sections = sections.to_crs(CRS).reset_index(drop=True)
    code = join_classes(sections, classes)
    edges = gpd.GeoDataFrame(
        {
            "section_id": sections["id"].astype("int64"),
            "source": sections["startjunctionid"].astype("int64"),
            "target": sections["endjunctionid"].astype("int64"),
            "name": sections["name"],
            "routeid": sections["routeid"].astype("int64"),
            "fairwayid": sections["fairwayid"],
            "km_begin": sections["routekmbegin"].astype(float),
            "km_end": sections["routekmend"].astype(float),
            "fis_km": sections["length"].astype(float),
            "cemt": code,
            "cemt_rank": code.map(cemt.RANK).astype("Int8"),
            "is_stub": (sections["routekmbegin"] == sections["routekmend"])
            & np.isclose(sections["length"], STUB_KM),
            "foreigncode": sections["foreigncode"],
        },
        geometry=sections.geometry.map(_single_line),
        crs=CRS,
    )
    if junctions is not None:
        edges = edges.set_geometry(_orient(edges, junctions.to_crs(CRS)))
    edges["length_m"] = edges.geometry.length
    return edges[COLUMNS]


def summarize(edges: gpd.GeoDataFrame) -> dict:
    """Counts and lengths that describe a built network."""
    routable = edges[~edges.is_stub]
    classified = routable[routable.cemt.notna()]
    return {
        "sections": int(len(edges)),
        "routable_sections": int(len(routable)),
        "stub_sections": int(edges.is_stub.sum()),
        "classified_sections": int(len(classified)),
        "routable_km": round(float(routable.length_m.sum()) / 1000, 1),
        "classified_km": round(float(classified.length_m.sum()) / 1000, 1),
        "km_by_class": {
            c: round(float(classified.length_m[classified.cemt == c].sum()) / 1000, 1)
            for c in cemt.CODES
            if (classified.cemt == c).any()
        },
    }


def build_from_dir(raw_dir: str | Path, out_path: str | Path) -> dict:
    """Build ``out_path`` (GeoParquet) from layers downloaded to ``raw_dir``.

    Writes ``<out_path stem>.json`` alongside with provenance and a summary,
    and returns that metadata.
    """
    raw = Path(raw_dir)
    junctions_path = raw / "junctions.geojson"
    edges = build_network(
        read_layer(raw / "sections.geojson"),
        gpd.read_file(raw / "classes.geojson"),
        read_layer(junctions_path) if junctions_path.exists() else None,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(out)

    meta = {
        "source": BASE_URL,
        "layers": {n: LAYERS[n] for n in ("sections", "classes", "junctions")},
        "licence": "CC-0, Rijkswaterstaat (Fairway Information Services)",
        "crs": f"EPSG:{CRS}",
        "downloaded": datetime.fromtimestamp(
            (raw / "sections.geojson").stat().st_mtime, timezone.utc
        ).isoformat(timespec="seconds"),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **summarize(edges),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta
