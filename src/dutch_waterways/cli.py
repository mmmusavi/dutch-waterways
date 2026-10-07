"""Command line: ``dutch-waterways download | build | route``."""

from __future__ import annotations

import argparse
import json
import sys

from . import fis

DEFAULT_RAW = "data/raw"
DEFAULT_NETWORK = "data/network.parquet"


def _point(text: str) -> tuple[float, float]:
    try:
        lon, lat = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected LON,LAT, got {text!r}") from None
    return lon, lat


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

    from .network import Network, NoRouteError

    net = Network.load(args.network)
    try:
        r = net.route(args.origin, args.destination, min_class=args.min_class)
    except NoRouteError as e:
        sys.exit(f"no route: {e}")
    print(f"distance:        {r.length_m / 1000:.1f} km along the fairways")
    print(
        f"access legs:     {r.origin.distance_m / 1000:.2f} km at origin, "
        f"{r.destination.distance_m / 1000:.2f} km at destination (straight line, not included)"
    )
    print(f"smallest class:  {r.smallest_class or 'unknown'}")
    print(f"sections:        {len(r.sections)}")
    if args.geojson:
        gpd.GeoDataFrame(
            {"length_m": [r.length_m], "smallest_class": [r.smallest_class]},
            geometry=[r.geometry_wgs84()],
            crs=4326,
        ).to_file(args.geojson, driver="GeoJSON")
        print(f"wrote {args.geojson}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dutch-waterways", description=__doc__)
    sub = p.add_subparsers(required=True)

    d = sub.add_parser("download", help="download FIS layers for the whole country")
    d.add_argument("--out", default=DEFAULT_RAW)
    d.add_argument("--all", action="store_true", help="also locks, bridges, depths, ...")
    d.set_defaults(func=_download)

    b = sub.add_parser("build", help="build the routable network from downloaded layers")
    b.add_argument("--raw", default=DEFAULT_RAW)
    b.add_argument("--out", default=DEFAULT_NETWORK)
    b.set_defaults(func=_build)

    r = sub.add_parser("route", help="route between two points")
    r.add_argument("origin", type=_point, help="LON,LAT")
    r.add_argument("destination", type=_point, help="LON,LAT")
    r.add_argument("--class", dest="min_class", help="smallest CEMT class allowed, e.g. I, IV, Va")
    r.add_argument("--network", default=DEFAULT_NETWORK)
    r.add_argument("--geojson", help="write the route line to this file")
    r.set_defaults(func=_route)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
