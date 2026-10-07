"""Bridges and locks on the network, and whether a vessel fits through them.

Each structure lies on one section and has zero or more *passages*: bridge
openings or lock chambers. A vessel gets through a structure when at least
one passage is wide, long and high enough for it. A dimension FIS does not
give is NaN and does not stop anyone; a structure without passages is
listed but never blocks.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import line_locate_point

from .build import CRS, as_line

COLUMNS = [
    "structure_id",
    "kind",  # "bridge" or "lock"
    "name",
    "section_id",
    "offset_m",  # along the section geometry from its source
    "movable",  # bridges: has an opening that opens
    "passage_width",  # per passage, metres
    "passage_length",
    "passage_clearance",  # inf for an opening that opens without a height limit
    "geometry",
]

# Opening types that do not open: fixed span and "OKW" (fixed passage under a
# structure). All others (OPH lift, BC bascule, DR swing, HEF vertical lift,
# ...) open; HEF and some others give a height limit when open.
FIXED_OPENINGS = {"VST", "OKW"}
EXISTING = {"CONSTRUCTED", "UNDER_CONSTRUCTION"}


def _positive(values) -> np.ndarray:
    v = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return np.where(v > 0, v, np.nan)


def _existing(df: pd.DataFrame) -> pd.DataFrame:
    if "condition" not in df:
        return df
    return df[df["condition"].isna() | df["condition"].isin(EXISTING)]


def _opening_passages(openings: gpd.GeoDataFrame) -> pd.DataFrame:
    o = _existing(openings)
    fixed = o["type"].isin(FIXED_OPENINGS).to_numpy()
    closed = _positive(o["clearanceheightclosed"])
    opened = _positive(o["clearanceheightopened"]) if "clearanceheightopened" in o else np.full(len(o), np.nan)
    clearance = np.where(fixed, closed, np.where(np.isnan(opened), np.inf, opened))
    return pd.DataFrame(
        {
            "structure_id": o["parentid"].astype("int64").to_numpy(),
            "section_id": o["fairwaysectionid"].astype("int64").to_numpy(),
            "width": _positive(o["width"]),
            "length": np.inf,
            "clearance": clearance,
            "movable": ~fixed,
            "name": o["name"].to_numpy(),
            "geometry": o.geometry.to_numpy(),
        }
    )


def _chamber_passages(chambers: gpd.GeoDataFrame) -> pd.DataFrame:
    c = _existing(chambers)
    # Usable length: the chamber length, or the (shorter) lockage length.
    length = np.fmin.reduce(
        [_positive(c[f]) for f in ("length", "schutlengteeb", "schutlengtevloed") if f in c]
    )
    width = np.fmin.reduce([_positive(c[f]) for f in ("gatewidth", "width") if f in c])
    return pd.DataFrame(
        {
            "structure_id": c["parentid"].astype("int64").to_numpy(),
            "section_id": c["fairwaysectionid"].astype("int64").to_numpy(),
            "width": width,
            "length": length,
            "clearance": np.inf,
            "movable": False,
            "name": c["name"].to_numpy(),
            "geometry": c.geometry.centroid.to_numpy(),
        }
    )


def _group(passages: pd.DataFrame, parents: gpd.GeoDataFrame | None, kind: str) -> pd.DataFrame:
    """One row per (structure, section), passages as lists."""
    rows = []
    names = {}
    if parents is not None:
        names = dict(zip(parents["id"].astype("int64"), parents["name"]))
    for (sid, section), g in passages.groupby(["structure_id", "section_id"], sort=False):
        pts = gpd.GeoSeries(g.geometry.to_list(), crs=CRS)
        rows.append(
            {
                "structure_id": sid,
                "kind": kind,
                "name": names.get(sid, g.name.iloc[0]),
                "section_id": section,
                "movable": bool(g.movable.any()),
                "passage_width": g.width.to_list(),
                "passage_length": g.length.to_list(),
                "passage_clearance": g.clearance.to_list(),
                "geometry": pts.union_all().centroid,
            }
        )
    return pd.DataFrame(rows)


def _without_passages(parents: gpd.GeoDataFrame | None, have: set, kind: str) -> pd.DataFrame:
    if parents is None:
        return pd.DataFrame()
    p = _existing(parents)
    p = p[~p["id"].astype("int64").isin(have)]
    return pd.DataFrame(
        {
            "structure_id": p["id"].astype("int64").to_numpy(),
            "kind": kind,
            "name": p["name"].to_numpy(),
            "section_id": p["fairwaysectionid"].astype("int64").to_numpy(),
            "movable": (p["canopen"] == "Yes").to_numpy() if "canopen" in p else False,
            "passage_width": [[] for _ in range(len(p))],
            "passage_length": [[] for _ in range(len(p))],
            "passage_clearance": [[] for _ in range(len(p))],
            "geometry": p.geometry.centroid.to_numpy(),
        }
    )


def build_structures(
    edges: gpd.GeoDataFrame,
    bridges: gpd.GeoDataFrame | None = None,
    openings: gpd.GeoDataFrame | None = None,
    locks: gpd.GeoDataFrame | None = None,
    chambers: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Bridges and locks on routable sections of ``edges``, in EPSG:28992.

    Bridges come from FIS ``opening`` records grouped by their parent (a
    bridge, or another structure such as an aqueduct); bridges without
    opening records are kept without passages. Locks come from ``sluiskolk``
    chambers grouped by their ``sluis``.
    """
    parts = []
    if openings is not None:
        op = _opening_passages(openings.to_crs(CRS))
        parts.append(_group(op, bridges, "bridge"))
        parts.append(_without_passages(bridges.to_crs(CRS) if bridges is not None else None,
                                       set(op.structure_id), "bridge"))
    if chambers is not None:
        ch = _chamber_passages(chambers.to_crs(CRS))
        parts.append(_group(ch, locks, "lock"))
        parts.append(_without_passages(locks.to_crs(CRS) if locks is not None else None,
                                       set(ch.structure_id), "lock"))
    parts = [p for p in parts if not p.empty]
    if not parts:
        return gpd.GeoDataFrame(columns=COLUMNS, geometry="geometry", crs=CRS)

    s = pd.concat(parts, ignore_index=True)
    routable = edges[~edges.is_stub].set_index("section_id")
    s = s[s.section_id.isin(routable.index)].reset_index(drop=True)
    lines = routable.geometry.loc[s.section_id].map(as_line).to_numpy()
    s["offset_m"] = line_locate_point(lines, s.geometry.to_numpy())
    s["movable"] = s.movable.astype(bool)
    return gpd.GeoDataFrame(s[COLUMNS], geometry="geometry", crs=CRS)


def passable(structures: pd.DataFrame, length=None, beam=None, air_draught=None) -> np.ndarray:
    """Whether a vessel of these dimensions fits through each structure."""
    out = np.ones(len(structures), dtype=bool)
    if length is None and beam is None and air_draught is None:
        return out
    for i, (w, ln, c) in enumerate(
        zip(structures.passage_width, structures.passage_length, structures.passage_clearance)
    ):
        if len(w) == 0:
            continue
        w, ln, c = (np.asarray(x, dtype=float) for x in (w, ln, c))
        fits = np.ones(len(w), dtype=bool)
        for have, need in ((w, beam), (ln, length), (c, air_draught)):
            if need is not None:
                fits &= np.isnan(have) | (have >= need)
        out[i] = fits.any()
    return out
