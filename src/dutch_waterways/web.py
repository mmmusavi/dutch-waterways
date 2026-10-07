"""Export the network as one compact JSON file for the browser router.

The file holds routable sections and structures in column-oriented arrays.
Coordinates are EPSG:28992 (RD New) metres, rounded to whole metres after a
light simplification; ``length`` keeps each section's full-resolution length,
so distances match the Python router.

Passage dimensions use ``null`` for "unknown" and for "no limit" alike: both
mean the passage does not restrict that dimension.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapely

from . import cemt
from .build import LIMITS, as_line

FORMAT = 1
SIMPLIFY_M = 5.0


def _num(v, digits=2):
    if v is None:
        return None
    v = float(v)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def to_json(network, simplify_m: float = SIMPLIFY_M) -> dict:
    """The network as a JSON-ready dict (see the module docstring)."""
    r = network._routable
    nodes = {n: i for i, n in enumerate(sorted(set(r.source) | set(r.target)))}
    lines = r.geometry.map(as_line)
    if simplify_m:
        lines = lines.map(lambda g: g.simplify(simplify_m))
    coords = [
        np.rint(np.asarray(shapely.get_coordinates(g))).astype(int).ravel().tolist() for g in lines
    ]
    edge_index = {label: i for i, label in enumerate(r.index)}
    edges = {
        "sectionId": r.section_id.astype(int).tolist(),
        "source": [nodes[n] for n in r.source],
        "target": [nodes[n] for n in r.target],
        "length": [round(float(v), 1) for v in r.length_m],
        "cemt": [int(v) if v == v else -1 for v in r.cemt_rank.astype(float)],
        "coords": coords,
    }
    for limit, key in zip(LIMITS, ("maxLength", "maxBeam", "maxDraught", "maxAirDraught")):
        edges[key] = [_num(v) for v in r[limit]] if limit in r else [None] * len(r)

    structures = {k: [] for k in ("edge", "kind", "name", "city", "offset", "movable", "x", "y", "passages")}
    if network.structures is not None:
        label_of = dict(zip(r.section_id, r.index))
        for s in network.structures.itertuples():
            label = label_of.get(s.section_id)
            if label is None:
                continue
            structures["edge"].append(edge_index[label])
            structures["kind"].append(s.kind)
            structures["name"].append(s.name)
            structures["city"].append(s.city if isinstance(s.city, str) and s.city else None)
            structures["offset"].append(round(float(s.offset_m), 1))
            structures["movable"].append(bool(s.movable))
            structures["x"].append(round(s.geometry.x))
            structures["y"].append(round(s.geometry.y))
            structures["passages"].append(
                [[_num(w), _num(ln), _num(c)] for w, ln, c in
                 zip(s.passage_width, s.passage_length, s.passage_clearance)]
            )

    return {
        "format": FORMAT,
        "crs": "EPSG:28992",
        "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Rijkswaterstaat, Fairway Information Services (CC-0)",
        "classes": list(cemt.CODES),
        "nodes": len(nodes),
        "edges": edges,
        "structures": structures,
    }


def export_web(network, out_path: str | Path, simplify_m: float = SIMPLIFY_M) -> Path:
    """Write :func:`to_json` to ``out_path``; return the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(to_json(network, simplify_m), separators=(",", ":"), ensure_ascii=False))
    return out
