"""Command line: ``dutch-waterways download | build | route | od``."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys

from . import data, fis

_LONLAT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _place(text: str):
    """``LON,LAT`` becomes a tuple; anything else is a place name."""
    m = _LONLAT.match(text)
    return (float(m[1]), float(m[2])) if m else text


def _network(args):
    from .network import Network

    if args.network:
        return Network.load(args.network)
    if not data.network_path().exists():
        print(f"building the network in {data.cache_dir()} (first run only)...", file=sys.stderr)
    return data.default_network()


def _vessel(args):
    from .network import Vessel

    return Vessel(args.min_class, args.length, args.beam, args.draught, args.air_draught)


def _download(args) -> None:
    layers = tuple(fis.LAYERS) if args.all else fis.CORE_LAYERS
    for name, path in fis.download(args.out, layers=layers).items():
        n = len(json.loads(path.read_text())["features"])
        print(f"{name:15} {n:6} features -> {path}")


def _build(args) -> None:
    from .build import build_from_dir

    meta = build_from_dir(args.raw, args.out)
    print(f"wrote {args.out}")
    print(json.dumps({k: v for k, v in meta.items() if k not in ("source", "layers")}, indent=2))


def _route(args) -> None:
    import geopandas as gpd

    from .network import NoRouteError

    try:
        r = _network(args).route(
            _place(args.origin), _place(args.destination), vessel=_vessel(args),
            access=args.access, max_access_m=args.max_access,
        )
    except (NoRouteError, LookupError) as e:
        sys.exit(f"no route: {e}")
    print(f"distance:        {r.length_m / 1000:.1f} km along the fairways")
    if r.min_class and args.access == "network":
        print(f"below class {r.min_class}:  {r.below_class_m / 1000:.1f} km of that")
    print(
        f"access legs:     {r.origin.distance_m / 1000:.2f} km at origin, "
        f"{r.destination.distance_m / 1000:.2f} km at destination (straight line, not included)"
    )
    print(f"smallest class:  {r.smallest_class or 'unknown'}")
    print(f"sections:        {len(r.sections)}")
    if r.structures is not None:
        bridges = r.bridges
        print(f"bridges:         {len(bridges)} ({int(bridges.movable.sum())} movable)")
        print(f"locks:           {len(r.locks)}")
        for _, s in r.locks.iterrows():
            print(f"  km {s.at_km:7.1f}  {s['name']}")
    limits = {k: v for k, v in r.limits().items() if v is not None}
    if limits:
        text = ", ".join(f"{k.replace('_', ' ')} {v:g} m" for k, v in limits.items())
        print(f"route allows:    {text}")
    if args.geojson:
        gpd.GeoDataFrame([r.summary()], geometry=[r.geometry_wgs84()], crs=4326).to_file(
            args.geojson, driver="GeoJSON"
        )
        print(f"wrote {args.geojson}")
    if args.map:
        r.to_map().save(args.map)
        print(f"wrote {args.map}")


def _read_places(path: str) -> dict:
    """CSV with a ``name`` column and optional ``lon``, ``lat`` columns."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    places = {}
    for row in rows:
        lon, lat = row.get("lon"), row.get("lat")
        places[row["name"]] = (float(lon), float(lat)) if lon and lat else row["name"]
    return places


def _od(args) -> None:
    from .network import NoRouteError

    if args.file:
        places = _read_places(args.file)
    else:
        places = {p: _place(p) for p in args.places}
    if len(places) < 2:
        sys.exit("give at least two places, or --file")
    try:
        m = _network(args).od_matrix(
            places, vessel=_vessel(args), access=args.access, max_access_m=args.max_access
        )
    except (NoRouteError, LookupError) as e:
        sys.exit(f"error: {e}")
    out = open(args.out, "w", newline="") if args.out else sys.stdout
    m.round(2).to_csv(out)
    if args.out:
        out.close()
        print(f"wrote {args.out}", file=sys.stderr)


def _routing_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--class", dest="min_class", help="smallest CEMT class allowed, e.g. I, IV, Va")
    p.add_argument(
        "--access", choices=("snap", "network"), default="snap",
        help="snap: join the nearest fairway of the class (default); "
        "network: reach it over smaller fairways, reported separately",
    )
    p.add_argument("--max-access", type=float, metavar="METRES",
                   help="fail if a place is further than this from the network")
    p.add_argument("--network", help="a network.parquet to use instead of the cached one")
    v = p.add_argument_group("vessel dimensions (metres)")
    v.add_argument("--length", type=float)
    v.add_argument("--beam", type=float)
    v.add_argument("--draught", type=float)
    v.add_argument("--air-draught", type=float, help="height above the waterline")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dutch-waterways", description=__doc__)
    sub = p.add_subparsers(required=True)

    d = sub.add_parser("download", help="download FIS layers for the whole country")
    d.add_argument("--out", default=str(data.raw_dir()))
    d.add_argument("--all", action="store_true", help="also locks, bridges, depths, ...")
    d.set_defaults(func=_download)

    b = sub.add_parser("build", help="build the routable network from downloaded layers")
    b.add_argument("--raw", default=str(data.raw_dir()))
    b.add_argument("--out", default=str(data.network_path()))
    b.set_defaults(func=_build)

    r = sub.add_parser("route", help="route between two places")
    r.add_argument("origin", help="place name or LON,LAT")
    r.add_argument("destination", help="place name or LON,LAT")
    _routing_options(r)
    r.add_argument("--geojson", help="write the route line to this file")
    r.add_argument("--map", help="write an HTML map to this file (needs folium)")
    r.set_defaults(func=_route)

    o = sub.add_parser("od", help="distance matrix (km) between places, as CSV")
    o.add_argument("places", nargs="*", help="place names or LON,LAT")
    o.add_argument("--file", help="CSV with a name column and optional lon, lat columns")
    o.add_argument("--out", help="write the CSV here instead of to stdout")
    _routing_options(o)
    o.set_defaults(func=_od)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
