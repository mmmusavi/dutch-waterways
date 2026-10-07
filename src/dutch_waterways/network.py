"""Route over a built network table (see :mod:`dutch_waterways.build`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import networkx as nx
from shapely import line_locate_point
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from . import cemt
from .build import CRS

# Graph node ids for the two ends of a query; FIS junction ids are positive.
_ORIGIN, _DESTINATION = -1, -2


class NoRouteError(Exception):
    """No route exists between the two points on the selected network."""


@dataclass(frozen=True)
class Snap:
    """Where a query point joins the network."""

    edge: int  # row label in Network.edges
    offset_m: float  # distance along the edge geometry from its source
    distance_m: float  # straight-line access leg from the query point
    point: Point  # the snapped point, EPSG:28992


@dataclass(frozen=True)
class Route:
    """A route between two points."""

    length_m: float  # along the fairways, between the two snapped points
    origin: Snap
    destination: Snap
    sections: gpd.GeoDataFrame  # the sections used, in order
    geometry: LineString  # EPSG:28992, origin to destination

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


def _as_point(p, crs) -> Point:
    """Project ``p`` ((lon, lat) or a shapely Point in ``crs``) to RD New."""
    pt = p if isinstance(p, Point) else Point(*p)
    return gpd.GeoSeries([pt], crs=crs).to_crs(CRS).iloc[0]


def _line(geom) -> LineString:
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        # Non-contiguous parts: join them in order, gaps become straight hops.
        return LineString([c for part in geom.geoms for c in part.coords])
    return geom


class Network:
    """A routable waterway network."""

    def __init__(self, edges: gpd.GeoDataFrame):
        self.edges = edges.to_crs(CRS)
        self._routable = self.edges[~self.edges.is_stub]

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

    def graph(self, min_class: str | int | None = None) -> nx.Graph:
        """An undirected graph of :meth:`select`, weighted by ``length``.

        Where junctions are joined by several sections the shortest is kept;
        the edge attribute ``edge`` holds its row label in :attr:`edges`.
        """
        g = nx.Graph()
        sel = self.select(min_class)
        for label, s, t, length in zip(sel.index, sel.source, sel.target, sel.length_m):
            if not g.has_edge(s, t) or g[s][t]["length"] > length:
                g.add_edge(s, t, length=length, edge=label)
        return g

    def snap(self, point, min_class: str | int | None = None, crs=4326) -> Snap:
        """Snap ``point`` ((lon, lat), or a Point in ``crs``) to the nearest section."""
        pt = _as_point(point, crs)
        sel = self.select(min_class)
        if sel.empty:
            raise NoRouteError(f"no sections of class {min_class} or larger")
        i = sel.sindex.nearest(pt)[1][0]  # on a tie, any nearest section will do
        label = sel.index[i]
        line = _line(sel.geometry.iloc[i])
        offset = float(line_locate_point(line, pt))
        return Snap(label, offset, pt.distance(line), line.interpolate(offset))

    def route(
        self,
        origin,
        destination,
        min_class: str | int | None = None,
        crs=4326,
    ) -> Route:
        """Shortest route between two points for a vessel of class ``min_class``.

        Points are (lon, lat) tuples, or shapely Points in ``crs``. Each is
        snapped to the nearest usable section; the straight-line access legs
        are reported in :attr:`Route.access_m`, not in :attr:`Route.length_m`.
        """
        a = self.snap(origin, min_class, crs)
        b = self.snap(destination, min_class, crs)
        g = self.graph(min_class)
        for node, snap in ((_ORIGIN, a), (_DESTINATION, b)):
            row = self.edges.loc[snap.edge]
            length = row.length_m
            g.add_edge(node, row.source, length=snap.offset_m, edge=snap.edge)
            g.add_edge(node, row.target, length=length - snap.offset_m, edge=snap.edge)

        if a.edge == b.edge:
            # Both points on one section: sailing along it is a candidate too.
            direct = abs(a.offset_m - b.offset_m)
            if not g.has_edge(_ORIGIN, _DESTINATION) or direct < g[_ORIGIN][_DESTINATION]["length"]:
                g.add_edge(_ORIGIN, _DESTINATION, length=direct, edge=a.edge)

        try:
            nodes = nx.shortest_path(g, _ORIGIN, _DESTINATION, weight="length")
        except nx.NetworkXNoPath:
            raise NoRouteError(
                f"no route for class {min_class} between {origin} and {destination}"
            ) from None

        labels, parts = [], []
        for u, v in zip(nodes, nodes[1:]):
            if g[u][v]["length"] == 0:
                continue  # query point sits on a junction; not sailed
            label = g[u][v]["edge"]
            labels.append(label)
            parts.append(self._piece(label, u, v, a, b))
        coords = []
        for part in parts:
            c = list(part.coords)
            coords.extend(c[1:] if coords and c and c[0] == coords[-1] else c)
        if not coords:
            coords = [a.point.coords[0]]
        if len(coords) == 1:
            coords *= 2

        return Route(
            length_m=nx.path_weight(g, nodes, "length"),
            origin=a,
            destination=b,
            sections=self.edges.loc[labels],
            geometry=LineString(coords),
        )

    def _piece(self, label, u, v, a: Snap, b: Snap) -> LineString:
        """Geometry of graph edge ``u -> v``, clipped at the snapped points."""
        row = self.edges.loc[label]
        line = _line(row.geometry)
        pos = {row.source: 0.0, row.target: line.length}
        if _ORIGIN in (u, v):
            pos[_ORIGIN] = a.offset_m
        if _DESTINATION in (u, v):
            pos[_DESTINATION] = b.offset_m
        start, end = pos[u], pos[v]
        if start <= end:
            return substring(line, start, end)
        return substring(line, end, start).reverse()
