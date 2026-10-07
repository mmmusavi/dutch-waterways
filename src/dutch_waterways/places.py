"""Turn places (names, coordinates, points) into points in RD New.

Place names are geocoded with OpenStreetMap's Nominatim. Its usage policy
asks for an identifying User-Agent, at most one request per second, and
caching; results are cached in memory and on disk (see :func:`cache_path`).
"""

from __future__ import annotations

import json
import threading
import time
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import Point

from .build import CRS
from .data import cache_dir

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = (
    f"dutch-waterways/{version('dutch-waterways')} "
    "(+https://github.com/mmmusavi/dutch-waterways)"
)
MIN_INTERVAL_S = 1.0

_lock = threading.Lock()
_last_request = 0.0
_memory: dict[str, tuple[float, float]] = {}


def cache_path() -> Path:
    return cache_dir() / "geocode.json"


def _read_disk() -> dict:
    try:
        return json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_disk(key: str, lonlat: tuple[float, float]) -> None:
    try:
        data = _read_disk()
        data[key] = lonlat
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        cache_path().write_text(json.dumps(data, indent=1, sort_keys=True))
    except OSError:
        pass  # the cache is a courtesy; geocoding still worked


def geocode(name: str, country: str | None = "nl", session=None) -> tuple[float, float]:
    """Return (lon, lat) for a place name, the best match Nominatim gives.

    ``country`` is an ISO 3166-1 code that limits the search (``None`` for
    anywhere). Raises :class:`LookupError` when nothing matches.
    """
    global _last_request
    key = f"{country or ''}|{' '.join(name.lower().split())}"
    if key in _memory:
        return _memory[key]
    disk = _read_disk().get(key)
    if disk:
        _memory[key] = tuple(disk)
        return _memory[key]

    params = {"q": name, "format": "jsonv2", "limit": 1}
    if country:
        params["countrycodes"] = country
    http = session or requests
    with _lock:
        wait = _last_request + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            r = http.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        finally:
            _last_request = time.monotonic()
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise LookupError(f"no place found for {name!r}")
    lonlat = (float(hits[0]["lon"]), float(hits[0]["lat"]))
    _memory[key] = lonlat
    _write_disk(key, lonlat)
    return lonlat


def resolve(place, crs=4326) -> tuple[str | None, Point]:
    """Return (label, point in EPSG:28992) for a place.

    ``place`` is a place name (label = the name), a (lon, lat) tuple, or a
    shapely Point in ``crs`` (label = None). Coordinate tuples are in ``crs``
    too, which is WGS84 by default.
    """
    if isinstance(place, str):
        label, pt, crs = place, Point(geocode(place)), 4326
    elif isinstance(place, Point):
        label, pt = None, place
    else:
        x, y = place
        label, pt = None, Point(float(x), float(y))
    return label, gpd.GeoSeries([pt], crs=crs).to_crs(CRS).iloc[0]
