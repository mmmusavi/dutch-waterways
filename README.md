# dutch-waterways

Route planner for Dutch inland waterways, built on Rijkswaterstaat's official
Fairway Information Services (FIS) network (open data, CC-0, no API key).

Give it an origin and a destination; get the sailing route along the marked
fairways, its length, and the smallest CEMT ship class on the way.

> Early development. Milestone 1 (network download, class join, basic routing)
> is done; place names, distance matrices, locks/bridges and the web map are
> next. See [PLAN.md](PLAN.md).

## Quick start

```sh
uv sync
uv run dutch-waterways download          # FIS sections, classes, junctions -> data/raw/
uv run dutch-waterways build             # -> data/network.parquet (+ .json summary)
uv run dutch-waterways route 5.0710,52.4950 5.3870,52.1610 --class I
```

```
distance:        73.0 km along the fairways
access legs:     1.36 km at origin, 0.25 km at destination (straight line, not included)
smallest class:  II
sections:        25
```

From Python:

```python
from dutch_waterways import Network

net = Network.load("data/network.parquet")
r = net.route((5.0710, 52.4950), (5.3870, 52.1610), min_class="I")
r.length_m, r.smallest_class, r.access_m
r.geometry_wgs84()   # shapely LineString
r.sections           # GeoDataFrame of the fairway sections used
```

`min_class` takes a CEMT class (`"I"`, `"IV"`, `"Va"`, `"VIb"`, ...). Without
it, every fairway counts, including small-craft canals and sections whose class
FIS does not give; with it, only sections of that class or larger are used.

## The network

`dutch-waterways build` writes one row per FIS fairway section (`vaarwegvak`),
in EPSG:28992 (RD New, metres):

| Column | Meaning |
|---|---|
| `section_id` | FIS section id |
| `source`, `target` | FIS junction ids; geometry runs from `source` to `target` |
| `length_m` | geometry length in metres (routing weight) |
| `fis_km` | length as given by FIS |
| `cemt`, `cemt_rank` | CEMT class (`_0` = small craft only) and its rank; empty if unknown |
| `routeid`, `km_begin`, `km_end` | FIS route and kilometre range |
| `is_stub` | placeholder link to a foreign network; never routed |

As built on 2026-10-07: 4,740 routable sections, 12,867 km, of which 8,521 km
have a CEMT class. All sections are two-way (`direction = H` throughout).

## Development

```sh
uv run pytest              # offline tests
uv run pytest -m online    # end-to-end against the live FIS service
```

## Licence

Code: [MIT](LICENSE). Network data: Rijkswaterstaat, Fairway Information
Services, CC-0.
