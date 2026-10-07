"""Route over a built network table (see :mod:`dutch_waterways.build`)."""

from __future__ import annotations

import warnings
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import line_locate_point
from shapely.geometry import LineString, Point
from shapely.ops import substring

from . import cemt
from .build import CRS, LIMITS, as_line, structures_path
from .structures import passable

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
class Vessel:
    """A vessel: its CEMT class and dimensions in metres.

    Anything left ``None`` is not checked. Sections and structures whose
    limits FIS does not give are assumed passable.
    """

    cemt: str | int | None = None
    length: float | None = None
    beam: float | None = None
    draught: float | None = None
    air_draught: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "cemt", cemt.normalize(self.cemt))

    @property
    def has_dimensions(self) -> bool:
        return any(v is not None for v in (self.length, self.beam, self.draught, self.air_draught))


def _vessel(min_class, vessel: Vessel | None) -> Vessel:
    v = vessel or Vessel()
    if min_class is not None:
        v = replace(v, cemt=cemt.normalize(min_class))
    return v


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
    vessel: Vessel = Vessel()
    below_class_m: float = 0.0  # part of length_m on fairways below the vessel's class
    structures: gpd.GeoDataFrame | None = None  # bridges and locks passed, in order

    @property
    def min_class(self) -> str | None:
        return self.vessel.cemt

    @property
    def access_m(self) -> float:
        """Straight-line distance from the query points to the network."""
        return self.origin.distance_m + self.destination.distance_m

    @property
    def smallest_class(self) -> str | None:
        """The smallest CEMT class on the route, or ``None`` if none is known."""
        ranks = self.sections.cemt_rank.dropna()
        return cemt.CODES[int(ranks.min())] if len(ranks) else None

    @property
    def locks(self) -> gpd.GeoDataFrame:
        return self._structures("lock")

    @property
    def bridges(self) -> gpd.GeoDataFrame:
        return self._structures("bridge")

    def _structures(self, kind):
        if self.structures is None:
            return gpd.GeoDataFrame()
        return self.structures[self.structures.kind == kind]

    def limits(self) -> dict:
        """The largest vessel this route takes, as far as FIS says (metres).

        Each value is the strictest of the section limits and the best
        passage of each structure on the route; ``None`` where nothing on the
        route gives that limit. Dimensions are taken one at a time: a bridge
        whose wide opening is low and whose high opening is narrow counts
        with its widest width and its greatest height.
        """
        out = {}
        for limit, dim in zip(LIMITS, ("length", "beam", "draught", "air_draught")):
            values = list(self.sections[limit].dropna()) if limit in self.sections else []
            column = {"length": "passage_length", "beam": "passage_width",
                      "air_draught": "passage_clearance"}.get(dim)
            if column and self.structures is not None:
                for passages in self.structures[column]:
                    p = np.asarray(passages, dtype=float)
                    if len(p) and not np.isnan(p).any():
                        values.append(p.max())
            finite = [v for v in values if np.isfinite(v)]
            out[dim] = round(float(min(finite)), 2) if finite else None
        return out

    def geometry_wgs84(self) -> LineString:
        return gpd.GeoSeries([self.geometry], crs=CRS).to_crs(4326).iloc[0]

    def summary(self) -> dict:
        """The route's key figures as plain values."""
        bridges = self.bridges
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
            "locks": len(self.locks),
            "bridges": len(bridges),
            "movable_bridges": int(bridges.movable.sum()) if len(bridges) else 0,
            **{f"max_{k}": v for k, v in self.limits().items()},
        }

    def to_map(self, **kwargs):
        """A Folium map of the route (needs ``pip install dutch-waterways[map]``)."""
        from .maps import route_map

        return route_map(self, **kwargs)


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
    """A routable waterway network, with its bridges and locks if known."""

    def __init__(self, edges: gpd.GeoDataFrame, structures: gpd.GeoDataFrame | None = None):
        self.edges = edges.to_crs(CRS)
        self.structures = structures.to_crs(CRS) if structures is not None else None
        self._routable = self.edges[~self.edges.is_stub]
        self._lines = self.edges.geometry.map(as_line)
        self._blocked_cache: dict[Vessel, np.ndarray] = {}
        self._on_section = {}
        if self.structures is not None:
            self._on_section = self.structures.groupby("section_id").indices

    @classmethod
    def load(cls, path: str | Path) -> Network:
        """Load a network built with :func:`dutch_waterways.build.build_from_dir`.

        Bridges and locks are loaded too when the structures file is there.
        """
        sp = structures_path(path)
        return cls(gpd.read_parquet(path), gpd.read_parquet(sp) if sp.exists() else None)

    def blocked(self, vessel: Vessel) -> pd.Series:
        """Which routable sections ``vessel`` cannot pass, by its dimensions.

        A section is blocked when one of its limits is below the vessel's
        dimension, or a bridge or lock on it has no passage the vessel fits.
        """
        dims = replace(vessel, cemt=None)
        if dims not in self._blocked_cache:
            r = self._routable
            out = np.zeros(len(r), dtype=bool)
            for limit, need in zip(LIMITS, (dims.length, dims.beam, dims.draught, dims.air_draught)):
                if need is not None and limit in r:
                    out |= (r[limit] < need).to_numpy()
            if self.structures is not None and dims.has_dimensions:
                ok = passable(self.structures, dims.length, dims.beam, dims.air_draught)
                stuck = set(self.structures.section_id[~ok])
                out |= r.section_id.isin(stuck).to_numpy()
            self._blocked_cache[dims] = out
        return pd.Series(self._blocked_cache[dims], index=self._routable.index)

    def select(self, min_class: str | int | None = None, vessel: Vessel | None = None) -> gpd.GeoDataFrame:
        """Routable sections a vessel can use.

        With no class every routable section counts, including small craft
        canals and sections without a known class. With a class (``min_class``
        or ``vessel.cemt``), only sections of that class or larger count. A
        vessel's dimensions remove the sections in :meth:`blocked`.
        """
        v = _vessel(min_class, vessel)
        sel = self._routable
        if v.has_dimensions:
            sel = sel[~self.blocked(v).to_numpy()]
        if v.cemt is not None:
            sel = sel[sel.cemt_rank.fillna(-1) >= cemt.rank(v.cemt)]
        return sel

    def graph(
        self,
        min_class: str | int | None = None,
        access: str = "snap",
        vessel: Vessel | None = None,
    ) -> nx.Graph:
        """An undirected graph of the network for a vessel.

        Edges carry ``length`` (metres), ``cost`` (the routing weight) and
        ``edge`` (row label in :attr:`edges`). With ``access="snap"`` only
        sections usable by the vessel's class are included and cost equals
        length. With ``access="network"`` sections below the class are
        included too, at :data:`BELOW_CLASS_PENALTY` times their length.
        Sections the vessel's dimensions do not fit are never included.
        Where junctions are joined by several sections the cheapest is kept.
        """
        _check_access(access)
        v = _vessel(min_class, vessel)
        sel = self.select(vessel=v if access == "snap" else replace(v, cemt=None))
        factor = self._factors(sel, v.cemt)
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

    def snap(
        self,
        point,
        min_class: str | int | None = None,
        crs=4326,
        vessel: Vessel | None = None,
    ) -> Snap:
        """Snap a place to the nearest section the vessel can use.

        ``point`` is a (lon, lat) tuple, a shapely Point in ``crs``, or a
        place name (geocoded with Nominatim, see :mod:`dutch_waterways.places`).
        """
        from .places import resolve

        label, pt = resolve(point, crs)
        sel = self.select(min_class, vessel)
        if sel.empty:
            raise NoRouteError("no sections fit this vessel")
        i = sel.sindex.nearest(pt)[1][0]  # on a tie, any nearest section will do
        edge = sel.index[i]
        line = self._lines.loc[edge]
        offset = float(line_locate_point(line, pt))
        return Snap(edge, offset, pt.distance(line), line.interpolate(offset), pt, label)

    def _query_graph(self, places, v: Vessel, access, max_access_m, crs):
        """The graph with query point ``k`` spliced in as node ``-(k + 1)``."""
        _check_access(access)
        snap_vessel = v if access == "snap" else replace(v, cemt=None)
        snaps = [self.snap(p, crs=crs, vessel=snap_vessel) for p in places]
        for s, p in zip(snaps, places):
            if max_access_m is not None and s.distance_m > max_access_m:
                raise TooFarError(
                    f"{s.label or p} is {s.distance_m:.0f} m from the nearest usable "
                    f"fairway (max_access_m={max_access_m:.0f})"
                )
        g = self.graph(access=access, vessel=v)

        on_edge = defaultdict(list)
        for k, s in enumerate(snaps):
            on_edge[s.edge].append((s.offset_m, -(k + 1)))
        for edge, points in on_edge.items():
            row = self.edges.loc[edge]
            line = self._lines.loc[edge]
            factor = self._factors(self.edges.loc[[edge]], v.cemt)[0] if access == "network" else 1.0
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
        vessel: Vessel | None = None,
        access: str = "snap",
        max_access_m: float | None = None,
        crs=4326,
    ) -> Route:
        """Shortest route between two places for a vessel.

        Places are (lon, lat) tuples, shapely Points in ``crs``, or place names.
        ``vessel`` gives the class and dimensions; ``min_class`` is a shortcut
        for the class alone (and overrides ``vessel.cemt``).

        ``access`` decides how a place reaches the network:

        - ``"snap"`` (default): the place joins the nearest section usable by
          the vessel; the straight-line leg to it is reported in
          :attr:`Route.access_m`, not in :attr:`Route.length_m`.
        - ``"network"``: the place joins the nearest fairway of any class the
          vessel fits, and the route uses fairways below the vessel's class
          only where it must. Their length is in :attr:`Route.below_class_m`.

        ``max_access_m`` raises :class:`TooFarError` for places further from
        the network than that.
        """
        v = self._checked(min_class, vessel)
        g, (a, b) = self._query_graph([origin, destination], v, access, max_access_m, crs)
        try:
            nodes = nx.shortest_path(g, -1, -2, weight="cost")
        except nx.NetworkXNoPath:
            raise NoRouteError(
                f"no route for {v} between {a.label or origin} and {b.label or destination}"
            ) from None

        legs = [(u, w, g[u][w]) for u, w in pairwise(nodes)]
        legs = [leg for leg in legs if leg[2]["length"] > 0]  # skip points on junctions
        labels = [d["edge"] for _, _, d in legs]
        lengths = np.array([d["length"] for _, _, d in legs])
        return Route(
            length_m=float(lengths.sum()),
            origin=a,
            destination=b,
            sections=self.edges.loc[labels],
            geometry=_join([self._piece(u, w, d) for u, w, d in legs], a.point),
            vessel=v,
            below_class_m=float(lengths[self._below(labels, v.cemt)].sum()),
            structures=self._passed(legs),
        )

    def _checked(self, min_class, vessel) -> Vessel:
        v = _vessel(min_class, vessel)
        if v.has_dimensions and (self.structures is None or "max_length" not in self.edges):
            warnings.warn(
                "this network has no bridge, lock or dimension data; vessel "
                "dimensions are not checked (rebuild it with this version)",
                stacklevel=3,
            )
        return v

    def _passed(self, legs) -> gpd.GeoDataFrame | None:
        """Structures on the route, in order, with ``at_km`` from the origin."""
        if self.structures is None:
            return None
        rows, at, done = [], 0.0, 0.0
        for u, w, d in legs:
            section = self.edges.at[d["edge"], "section_id"]
            idx = self._on_section.get(section)
            if idx is not None:
                start, end = self._span(u, w, d)
                lo, hi = min(start, end), max(start, end)
                offsets = self.structures.offset_m.to_numpy()[idx]
                inside = (offsets >= lo - 1e-6) & (offsets <= hi + 1e-6)
                for i, off in zip(idx[inside], offsets[inside]):
                    rows.append((i, done + abs(off - start)))
            done += d["length"]
        if not rows:
            return self.structures.iloc[[]].assign(at_km=[])
        order = sorted(rows, key=lambda r: r[1])
        out = self.structures.iloc[[i for i, _ in order]].copy()
        out["at_km"] = [round(a / 1000, 3) for _, a in order]
        return out

    def od_matrix(
        self,
        places,
        min_class: str | int | None = None,
        vessel: Vessel | None = None,
        access: str = "snap",
        max_access_m: float | None = None,
        crs=4326,
    ) -> pd.DataFrame:
        """Fairway distances in km between every pair of ``places``.

        ``places`` is a list of places (as in :meth:`route`) or a dict of
        ``{label: place}``. Unreachable pairs are NaN. ``vessel``, ``access``
        and ``max_access_m`` work as in :meth:`route`; the straight-line
        access legs are in ``result.attrs["access_km"]`` and, with
        ``access="network"``, the km below the vessel's class per pair in
        ``result.attrs["below_class_km"]``.
        """
        if isinstance(places, dict):
            labels, places = list(places), list(places.values())
        else:
            places = list(places)
            labels = None
        v = self._checked(min_class, vessel)
        g, snaps = self._query_graph(places, v, access, max_access_m, crs)
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
                legs = [g[u][w] for u, w in pairwise(path)]
                lengths = np.array([d["length"] for d in legs])
                dist[i, j] = lengths.sum() / 1000
                below[i, j] = lengths[self._below([d["edge"] for d in legs], v.cemt)].sum() / 1000

        out = pd.DataFrame(dist, index=labels, columns=labels)
        out.attrs["access_km"] = pd.Series([s.distance_m / 1000 for s in snaps], index=labels)
        if access == "network":
            out.attrs["below_class_km"] = pd.DataFrame(below, index=labels, columns=labels)
        return out

    def _span(self, u, w, data) -> tuple[float, float]:
        """Offsets along the section where graph edge ``u -> w`` starts and ends."""
        row = self.edges.loc[data["edge"]]
        pos = data.get("pos") or {row.source: 0.0, row.target: self._lines.loc[data["edge"]].length}
        return pos[u], pos[w]

    def _piece(self, u, w, data) -> LineString:
        """Geometry of graph edge ``u -> w``, clipped at spliced query points."""
        line = self._lines.loc[data["edge"]]
        start, end = self._span(u, w, data)
        if start <= end:
            return substring(line, start, end)
        return substring(line, end, start).reverse()


def _check_access(access: str) -> None:
    if access not in ACCESS_MODES:
        raise ValueError(f"access must be one of {ACCESS_MODES}, got {access!r}")
