"""Folium maps of routes. Needs ``pip install dutch-waterways[map]``."""

from __future__ import annotations

from html import escape

import geopandas as gpd
from shapely.geometry import LineString

from . import cemt
from .build import CRS

ROUTE_COLOR = "#1f6feb"
BELOW_CLASS_COLOR = "#d97706"
ACCESS_COLOR = "#6b7280"


def _folium():
    try:
        import folium
    except ImportError:
        raise ImportError(
            "maps need folium: pip install 'dutch-waterways[map]'"
        ) from None
    return folium


def _latlon(geom) -> list[tuple[float, float]]:
    g = gpd.GeoSeries([geom], crs=CRS).to_crs(4326).iloc[0]
    return [(y, x) for x, y in g.coords]


def _popup(route) -> str:
    s = route.summary()
    rows = [
        ("Distance", f"{s['length_km']:.1f} km"),
        ("Smallest class", s["smallest_class"] or "unknown"),
        ("Access legs", f"{s['access_origin_km']:.2f} + {s['access_destination_km']:.2f} km (straight line)"),
    ]
    if route.min_class:
        rows.insert(1, ("Vessel class", route.min_class))
        if route.below_class_m:
            rows.append(("Below vessel class", f"{s['below_class_km']:.1f} km"))
    body = "".join(f"<tr><th align=left>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def route_map(route, m=None, tiles: str = "OpenStreetMap"):
    """Draw ``route`` on a Folium map (a new one unless ``m`` is given).

    The route is blue; sections below the vessel class (``access="network"``)
    are orange; straight-line access legs are dashed grey.
    """
    folium = _folium()
    line = _latlon(route.geometry)
    if m is None:
        m = folium.Map(tiles=tiles)
        lats, lons = zip(*line)
        m.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))])

    popup = folium.Popup(_popup(route), max_width=320)
    folium.PolyLine(line, color=ROUTE_COLOR, weight=5, opacity=0.85, popup=popup).add_to(m)

    if route.min_class and route.below_class_m:
        below = route.sections[route.sections.cemt_rank.fillna(-1) < cemt.rank(route.min_class)]
        for geom, code in zip(below.geometry.intersection(route.geometry.buffer(1)), below.cemt):
            for part in getattr(geom, "geoms", [geom]):
                if isinstance(part, LineString) and not part.is_empty:
                    folium.PolyLine(
                        _latlon(part), color=BELOW_CLASS_COLOR, weight=6,
                        tooltip=f"class {code or 'unknown'}, below {route.min_class}",
                    ).add_to(m)

    for snap, name, icon in (
        (route.origin, "Origin", "play"),
        (route.destination, "Destination", "stop"),
    ):
        if snap.distance_m > 1:
            folium.PolyLine(
                _latlon(LineString([snap.query, snap.point])),
                color=ACCESS_COLOR, weight=3, dash_array="6 6",
                tooltip=f"access leg {snap.distance_m / 1000:.2f} km",
            ).add_to(m)
        label = f"{name}: {snap.label}" if snap.label else name
        folium.Marker(_latlon(snap.query)[0], tooltip=label, icon=folium.Icon(icon=icon)).add_to(m)
    return m
