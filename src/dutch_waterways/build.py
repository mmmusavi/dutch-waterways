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

# Bumped when the built files change shape; older cached builds are rebuilt.
FORMAT = 3

# FIS models links into foreign networks as zero-km sections whose geometry is
# a straight placeholder line, sometimes hundreds of km long. They are kept in
# the table for reference but are not routable.
STUB_KM = 0.103

# Section limits, and the fields that give them in each FIS layer.
LIMITS = ("max_length", "max_beam", "max_draught", "max_air_draught")
LIMIT_FIELDS = {
    "max_dimensions": {  # layer 37, legal maximum dimensions
        "generallength": "max_length",
        "generalwidth": "max_beam",
        "generaldepth": "max_draught",
        "generalheight": "max_air_draught",
    },
    "visuris_dimensions": {  # layer 200, VisuRIS maximum dimensions
        "maxlength": "max_length",
        "maxwidth": "max_beam",
    },
}


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
    *LIMITS,
    "geometry",
]


def read_layer(path: str | Path) -> gpd.GeoDataFrame:
    """Read a downloaded FIS GeoJSON layer and project it to RD New."""
    return gpd.read_file(path).to_crs(CRS)


def km_overlaps(sections: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    """Pair sections with the records on the same ``routeid`` that cover them.

    Both frames have ``routeid``, ``routekmbegin`` and ``routekmend``. Returns
    ``row`` (position in ``sections``), ``rec`` (position in ``records``) and
    ``overlap`` in km. A section with an empty km range pairs with the records
    that contain its km point (overlap 0).
    """
    rec = pd.DataFrame(
        {
            "rec": np.arange(len(records)),
            "routeid": records["routeid"].to_numpy(),
            "c_lo": np.minimum(records["routekmbegin"], records["routekmend"]),
            "c_hi": np.maximum(records["routekmbegin"], records["routekmend"]),
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
    m = sec.merge(rec, on="routeid")
    m["overlap"] = np.minimum(m.s_hi, m.c_hi) - np.maximum(m.s_lo, m.c_lo)
    point = m.s_hi == m.s_lo
    hit = np.where(point, (m.c_lo <= m.s_lo) & (m.s_lo <= m.c_hi), m.overlap > 1e-9)
    return m.loc[hit, ["row", "rec", "overlap"]].reset_index(drop=True)


def join_classes(sections: pd.DataFrame, classes: pd.DataFrame) -> pd.Series:
    """Return the CEMT code of each section (``None`` where unknown).

    A section takes the class of the class record on the same ``routeid``
    whose km range overlaps it most. Sections with an empty km range take the
    record that contains their km point. On equal overlap the smaller class
    wins, to stay on the safe side.
    """
    codes = classes["code"].map(cemt.normalize).to_numpy()
    m = km_overlaps(sections, classes)
    m["code"] = codes[m.rec.to_numpy()]
    m["rank"] = m.code.map(cemt.RANK)
    best = m.sort_values(["row", "overlap", "rank"], ascending=[True, False, True])
    best = best.drop_duplicates("row").set_index("row")["code"]

    out = pd.Series([None] * len(sections), index=sections.index, dtype=object)
    out.iloc[best.index.to_numpy()] = best.to_numpy()
    return out


def join_limits(sections: pd.DataFrame, **layers: pd.DataFrame) -> pd.DataFrame:
    """Maximum vessel dimensions per section, in metres (NaN where unknown).

    ``layers`` maps names in :data:`LIMIT_FIELDS` to their FIS records. Each
    limit is the strictest of all records that overlap the section.
    """
    out = pd.DataFrame(np.nan, index=sections.index, columns=list(LIMITS))
    for name, records in layers.items():
        if records is None or records.empty:
            continue
        m = km_overlaps(sections, records)
        for field, limit in LIMIT_FIELDS[name].items():
            if field not in records:
                continue
            values = pd.to_numeric(records[field], errors="coerce").to_numpy()
            v = pd.Series(values[m.rec.to_numpy()], index=m.row.to_numpy())
            v = v[v > 0].groupby(level=0).min()
            current = out[limit].to_numpy(copy=True)
            current[v.index] = np.fmin(current[v.index], v.to_numpy())
            out[limit] = current
    return out


def as_line(geom) -> LineString:
    """One LineString for a section; gaps between non-contiguous parts become
    straight hops. Offsets along sections are measured on this line."""
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        return LineString([c for part in geom.geoms for c in part.coords])
    return geom


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
    max_dimensions: pd.DataFrame | None = None,
    visuris_dimensions: pd.DataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Build the network table from FIS sections, classes and junctions.

    Inputs are FIS layers as read by :func:`read_layer`. ``junctions`` is used
    to orient each geometry from ``source`` to ``target``; without it the FIS
    orientation is kept as is. The dimension layers give each section's
    maximum vessel length, beam, draught and air draught (see
    :func:`join_limits`).
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
    limits = join_limits(
        sections, max_dimensions=max_dimensions, visuris_dimensions=visuris_dimensions
    )
    edges = edges.join(limits)
    if junctions is not None:
        edges = edges.set_geometry(_orient(edges, junctions.to_crs(CRS)))
    edges["length_m"] = edges.geometry.length
    return edges[COLUMNS]


def summarize(edges: gpd.GeoDataFrame, structures: pd.DataFrame | None = None) -> dict:
    """Counts and lengths that describe a built network."""
    routable = edges[~edges.is_stub]
    classified = routable[routable.cemt.notna()]
    out = {
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
        "km_with_limit": {
            limit: round(float(routable.length_m[routable[limit].notna()].sum()) / 1000, 1)
            for limit in LIMITS
            if limit in routable
        },
    }
    if structures is not None:
        out["structures"] = {
            kind: int((structures.kind == kind).sum()) for kind in ("bridge", "lock")
        }
    return out


def structures_path(network_path: str | Path) -> Path:
    """Where the structures table of a network file lives."""
    p = Path(network_path)
    return p.with_name(f"{p.stem}.structures.parquet")


def build_from_dir(raw_dir: str | Path, out_path: str | Path) -> dict:
    """Build ``out_path`` (GeoParquet) from layers downloaded to ``raw_dir``.

    Also writes the bridges and locks to :func:`structures_path` when their
    layers were downloaded, and ``<out_path stem>.json`` with provenance and
    a summary. Returns that metadata.
    """
    from .structures import build_structures

    raw = Path(raw_dir)

    def layer(name, project=True):
        path = raw / f"{name}.geojson"
        if not path.exists():
            return None
        return read_layer(path) if project else gpd.read_file(path)

    edges = build_network(
        read_layer(raw / "sections.geojson"),
        gpd.read_file(raw / "classes.geojson"),
        layer("junctions"),
        max_dimensions=layer("max_dimensions", project=False),
        visuris_dimensions=layer("visuris_dimensions", project=False),
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(out)

    structures = None
    if (raw / "openings.geojson").exists() or (raw / "lock_chambers.geojson").exists():
        structures = build_structures(
            edges,
            bridges=layer("bridges"),
            openings=layer("openings"),
            locks=layer("locks"),
            chambers=layer("lock_chambers"),
        )
        structures.to_parquet(structures_path(out))

    used = [n for n in LAYERS if (raw / f"{n}.geojson").exists()]
    meta = {
        "format": FORMAT,
        "source": BASE_URL,
        "layers": {n: LAYERS[n] for n in used},
        "licence": "CC-0, Rijkswaterstaat (Fairway Information Services)",
        "crs": f"EPSG:{CRS}",
        "downloaded": datetime.fromtimestamp(
            (raw / "sections.geojson").stat().st_mtime, timezone.utc
        ).isoformat(timespec="seconds"),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **summarize(edges, structures),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta
