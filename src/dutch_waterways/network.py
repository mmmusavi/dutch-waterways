"""Route over a built network table (see :mod:`dutch_waterways.build`)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import line_locate_point
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from . import cemt
from .build import CRS

ACCESS_MODES = ("snap", "network")

# With access="network", a metre of fairway below the requested class costs
# this many metres of fairway of that class: routes use as little of it as
# they can.
BELOW_CLASS_PENALTY = 1000.0


class NoRouteError(Exception):
    """No route exists between the two points on the selected network."""


class TooFarError(NoRouteError):
    """A point is further from the network than ``max_access_m`` allows."""


@dataclass(frozen=True)
class Snap:
    """Where a query point joins the network."""

    edge: int  # row label in Network.edges
    offset_m: float  # distance along the edge geometry from its source
    distance_m: float  # straight-line access leg from the query point
    point: Point  # the snapped point, EPSG:28992
    query: Point  # the query point, EPSG:28992
    label: str | None = None  # the place name, if one was given


@dataclass(frozen=True)
class Route:
    """A route between two points."""

    length_m: float  # along the fairways, between the two snapped points
    origin: Snap
    destination: Snap
    sections: gpd.GeoDataFrame  # the sections used, in order
    geometry: LineString  # EPSG:28992, origin to destination
    min_class: str | None = None
    below_class_m: float = 0.0  # part of length_m on fairways below min_class

    @property
    def access_m(self) -> float:
        """Straight-line distance from the query points to the network."""
        return self.origin.distance_m + self.destination.distance_m

    @property
    def smallest_class(self) -> str | None:
        """The smallest CEMT class on the route, or ``None`` if none is known."""
        ranks = self.sections.cemt_rank.dropna()
        return cemt.CODES[int(ranks.min())] if len(ranks) else None

    def geometry_wgs84(self) -> LineString:
        return gpd.GeoSeries([self.geometry], crs=CRS).to_crs(4326).iloc[0]

    def summary(self) -> dict:
        """The route's key figures as plain values."""
        return {
            "origin": self.origin.label,
            "destination": self.destination.label,
            "length_km": round(self.length_m / 1000, 2),
            "access_origin_km": round(self.origin.distance_m / 1000, 2),
            "access_destination_km": round(self.destination.distance_m / 1000, 2),
            "min_class": self.min_class,
            "smallest_class": self.smallest_class,
            "below_class_km": round(self.below_class_m / 1000, 2),
            "sections": len(self.sections),
        }

    def to_map(self, **kwargs):
        """A Folium map of the route (needs ``pip install dutch-waterways[map]``)."""
        from .maps import route_map

        return route_map(self, **kwargs)


def _line(geom) -> LineString:
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        # Non-contiguous parts: join them in order, gaps become straight hops.
        return LineString([c for part in geom.geoms for c in part.coords])
    return geom


def _join(parts: list[LineString], fallback: Point) -> LineString:
    coords: list[tuple] = []
    for part in parts:
        c = list(part.coords)
        coords.extend(c[1:] if coords and c and c[0] == coords[-1] else c)
    if not coords:
        coords = [fallback.coords[0]]
    if len(coords) == 1:
        coords *= 2
    return LineString(coords)


class Network:
    """A routable waterway network."""

    def __init__(self, edges: gpd.GeoDataFrame):
        self.edges = edges.to_crs(CRS)
        self._routable = self.edges[~self.edges.is_stub]
        self._lines = self.edges.geometry.map(_line)

    @classmethod
    def load(cls, path: str | Path) -> Network:
        """Load a network built with :func:`dutch_waterways.build.build_from_dir`."""
        return cls(gpd.read_parquet(path))

    def select(self, min_class: str | int | None = None) -> gpd.GeoDataFrame:
        """Routable sections usable by a vessel of CEMT class ``min_class``.

        With ``min_class=None`` every routable section counts, including small
        craft canals and sections without a known class. With a class, only
        sections of that class or larger count.
        """
        if min_class is None:
            return self._routable
        r = cemt.rank(min_class)
        return self._routable[self._routable.cemt_rank.fillna(-1) >= r]

    def graph(self, min_class: str | int | None = None, access: str = "snap") -> nx.Graph:
        """An undirected graph of the network for a vessel of class ``min_class``.

        Edges carry ``length`` (metres), ``cost`` (the routing weight) and
        ``edge`` (row label in :attr:`edges`). With ``access="snap"`` only
        usable sections are included and cost equals length. With
        ``access="network"`` all routable sections are included and those
        below ``min_class`` cost :data:`BELOW_CLASS_PENALTY` times their length.
        Where junctions are joined by several sections the cheapest is kept.
        """
        _check_access(access)
        sel = self.select(min_class if access == "snap" else None)
        factor = self._factors(sel, min_class)
        g = nx.Graph()
        for label, s, t, length, f in zip(sel.index, sel.source, sel.target, sel.length_m, factor):
            cost = length * f
            if not g.has_edge(s, t) or g[s][t]["cost"] > cost:
                g.add_edge(s, t, length=length, cost=cost, edge=label)
        return g

    def _factors(self, sel: pd.DataFrame, min_class) -> np.ndarray:
        if min_class is None:
            return np.ones(len(sel))
        usable = sel.cemt_rank.fillna(-1).to_numpy() >= cemt.rank(min_class)
        return np.where(usable, 1.0, BELOW_CLASS_PENALTY)

    def snap(self, point, min_class: str | int | None = None, crs=4326) -> Snap:
        """Snap a place to the nearest section usable by class ``min_class``.

        ``point`` is a (lon, lat) tuple, a shapely Point in ``crs``, or a
        place name (geocoded with Nominatim, see :mod:`dutch_waterways.places`).
        """
        from .places import resolve

        label, pt = resolve(point, crs)
        sel = self.select(min_class)
        if sel.empty:
            raise NoRouteError(f"no sections of class {min_class} or larger")
        i = sel.sindex.nearest(pt)[1][0]  # on a tie, any nearest section will do
        edge = sel.index[i]
        line = self._lines.loc[edge]
        offset = float(line_locate_point(line, pt))
        return Snap(edge, offset, pt.distance(line), line.interpolate(offset), pt, label)

    def _query_graph(self, places, min_class, access, max_access_m, crs):
        """The graph with query point ``k`` spliced in as node ``-(k + 1)``."""
        _check_access(access)
        snap_class = min_class if access == "snap" else None
        snaps = [self.snap(p, snap_class, crs) for p in places]
        for s, p in zip(snaps, places):
            if max_access_m is not None and s.distance_m > max_access_m:
                raise TooFarError(
                    f"{s.label or p} is {s.distance_m:.0f} m from the nearest usable "
                    f"fairway (max_access_m={max_access_m:.0f})"
                )
        g = self.graph(min_class, access)

        on_edge = defaultdict(list)
        for k, s in enumerate(snaps):
            on_edge[s.edge].append((s.offset_m, -(k + 1)))
        for edge, points in on_edge.items():
            row = self.edges.loc[edge]
            line = self._lines.loc[edge]
            factor = self._factors(self.edges.loc[[edge]], min_class)[0] if access == "network" else 1.0
            if g.has_edge(row.source, row.target) and g[row.source][row.target]["edge"] == edge:
                g.remove_edge(row.source, row.target)
            chain = [(0.0, row.source), *sorted(points), (line.length, row.target)]
            for (o1, n1), (o2, n2) in pairwise(chain):
                length = o2 - o1
                g.add_edge(n1, n2, length=length, cost=length * factor, edge=edge, pos={n1: o1, n2: o2})
        return g, snaps

    def _below(self, labels, min_class) -> np.ndarray:
        if min_class is None:
            return np.zeros(len(labels), dtype=bool)
        ranks = self.edges.loc[labels, "cemt_rank"].fillna(-1).to_numpy()
        return ranks < cemt.rank(min_class)

    def route(
        self,
        origin,
        destination,
        min_class: str | int | None = None,
        access: str = "snap",
        max_access_m: float | None = None,
        crs=4326,
    ) -> Route:
        """Shortest route between two places for a vessel of class ``min_class``.

        Places are (lon, lat) tuples, shapely Points in ``crs``, or place names.

        ``access`` decides how a place reaches the network:

        - ``"snap"`` (default): the place joins the nearest section usable by
          ``min_class``; the straight-line leg to it is reported in
          :attr:`Route.access_m`, not in :attr:`Route.length_m`.
        - ``"network"``: the place joins the nearest fairway of any class, and
          the route uses fairways below ``min_class`` only where it must. Their
          length is in :attr:`Route.below_class_m`.

        ``max_access_m`` raises :class:`TooFarError` for places further from
        the network than that.
        """
        g, (a, b) = self._query_graph([origin, destination], min_class, access, max_access_m, crs)
        try:
            nodes = nx.shortest_path(g, -1, -2, weight="cost")
        except nx.NetworkXNoPath:
            raise NoRouteError(
                f"no route for class {min_class} between {a.label or origin} and "
                f"{b.label or destination}"
            ) from None

        legs = [(u, v, g[u][v]) for u, v in pairwise(nodes)]
        legs = [leg for leg in legs if leg[2]["length"] > 0]  # skip points on junctions
        labels = [d["edge"] for _, _, d in legs]
        lengths = np.array([d["length"] for _, _, d in legs])
        return Route(
            length_m=float(lengths.sum()),
            origin=a,
            destination=b,
            sections=self.edges.loc[labels],
            geometry=_join([self._piece(u, v, d) for u, v, d in legs], a.point),
            min_class=cemt.normalize(min_class),
            below_class_m=float(lengths[self._below(labels, min_class)].sum()),
        )

    def od_matrix(
        self,
        places,
        min_class: str | int | None = None,
        access: str = "snap",
        max_access_m: float | None = None,
        crs=4326,
    ) -> pd.DataFrame:
        """Fairway distances in km between every pair of ``places``.

        ``places`` is a list of places (as in :meth:`route`) or a dict of
        ``{label: place}``. Unreachable pairs are NaN. ``access`` and
        ``max_access_m`` work as in :meth:`route`; the straight-line access
        legs are in ``result.attrs["access_km"]`` and, with
        ``access="network"``, the km below ``min_class`` per pair in
        ``result.attrs["below_class_km"]``.
        """
        if isinstance(places, dict):
            labels, places = list(places), list(places.values())
        else:
            places = list(places)
            labels = None
        g, snaps = self._query_graph(places, min_class, access, max_access_m, crs)
        if labels is None:
            labels = [s.label or str(p) for s, p in zip(snaps, places)]

        n = len(places)
        dist = np.full((n, n), np.nan)
        below = np.full((n, n), np.nan)
        for i in range(n):
            _, paths = nx.single_source_dijkstra(g, -(i + 1), weight="cost")
            for j in range(n):
                path = paths.get(-(j + 1))
                if path is None:
                    continue
                legs = [g[u][v] for u, v in pairwise(path)]
                lengths = np.array([d["length"] for d in legs])
                dist[i, j] = lengths.sum() / 1000
                below[i, j] = lengths[self._below([d["edge"] for d in legs], min_class)].sum() / 1000

        out = pd.DataFrame(dist, index=labels, columns=labels)
        out.attrs["access_km"] = pd.Series([s.distance_m / 1000 for s in snaps], index=labels)
        if access == "network":
            out.attrs["below_class_km"] = pd.DataFrame(below, index=labels, columns=labels)
        return out

    def _piece(self, u, v, data) -> LineString:
        """Geometry of graph edge ``u -> v``, clipped at spliced query points."""
        row = self.edges.loc[data["edge"]]
        line = self._lines.loc[data["edge"]]
        pos = data.get("pos") or {row.source: 0.0, row.target: line.length}
        start, end = pos[u], pos[v]
        if start <= end:
            return substring(line, start, end)
        return substring(line, end, start).reverse()


def _check_access(access: str) -> None:
    if access not in ACCESS_MODES:
        raise ValueError(f"access must be one of {ACCESS_MODES}, got {access!r}")
