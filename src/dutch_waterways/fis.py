"""Download layers from Rijkswaterstaat's Fairway Information Services (FIS).

The service is open data (CC-0) and needs no API key. Each layer is fetched as
GeoJSON in WGS84, page by page.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE_URL = "https://geo.rijkswaterstaat.nl/arcgis/rest/services/GDR/fis_vnds/MapServer"

# Layer ids in the fis_vnds MapServer. Names are our own; the service's
# spelling of some (e.g. "scheeepvaartklasse") is irregular.
LAYERS = {
    "sections": 58,  # vaarwegvak: the routable network
    "classes": 49,  # scheeepvaartklasse: CEMT class per routeid + km range
    "junctions": 24,  # vaarwegjunctie
    "locks": 64,  # sluis_v: locks (polygons; layer 19 holds foreign locks only)
    "lock_chambers": 65,  # sluiskolk_v: chamber length, width, sill depth
    "bridges": 3,  # brug
    "openings": 15,  # opening: per bridge opening, width and clearance
    "max_dimensions": 37,  # max_toegestane_afmeting: legal max length, width, draught, height
    "visuris_dimensions": 200,  # maximale dimensies visuris: max length, width
    "depths": 54,  # vaarwegdiepte
    "route_planning": 197,  # routeplanning
}

# What the network build uses.
CORE_LAYERS = (
    "sections", "classes", "junctions", "locks", "lock_chambers",
    "bridges", "openings", "max_dimensions", "visuris_dimensions",
)

PAGE_SIZE = 1000


def fetch_layer(
    layer: str | int,
    bbox: tuple[float, float, float, float] | None = None,
    session: requests.Session | None = None,
    page_size: int = PAGE_SIZE,
    timeout: float = 120,
) -> dict:
    """Return one FIS layer as a GeoJSON FeatureCollection (WGS84).

    ``layer`` is a name from :data:`LAYERS` or a numeric layer id. ``bbox`` is
    ``(min_lon, min_lat, max_lon, max_lat)``; without it the whole layer is
    fetched.
    """
    layer_id = LAYERS[layer] if isinstance(layer, str) else layer
    http = session or requests.Session()
    params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": 4326,
        "orderByFields": "objectid",  # stable paging
        "resultRecordCount": page_size,
        "f": "geojson",
    }
    if bbox is not None:
        params.update(
            geometry=",".join(str(v) for v in bbox),
            geometryType="esriGeometryEnvelope",
            inSR=4326,
            spatialRel="esriSpatialRelIntersects",
        )

    features: list[dict] = []
    while True:
        params["resultOffset"] = len(features)
        r = http.get(f"{BASE_URL}/{layer_id}/query", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"FIS layer {layer_id}: {data['error']}")
        page = data.get("features", [])
        features.extend(page)
        more = data.get("exceededTransferLimit") or data.get("properties", {}).get(
            "exceededTransferLimit"
        )
        if not page or (not more and len(page) < page_size):
            break
    return {"type": "FeatureCollection", "features": features}


def download(
    out_dir: str | Path,
    layers: tuple[str, ...] = CORE_LAYERS,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Path]:
    """Download ``layers`` to ``out_dir/<name>.geojson``; return the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    with requests.Session() as session:
        for name in layers:
            fc = fetch_layer(name, bbox=bbox, session=session)
            path = out / f"{name}.geojson"
            path.write_text(json.dumps(fc))
            paths[name] = path
    return paths
