# dutch-waterways

Route planner for Dutch inland waterways, built on Rijkswaterstaat's official
Fairway Information Services (FIS) network (open data, CC-0, no API key).

Give it an origin and a destination; get the sailing route along the marked
fairways, its length, and the smallest CEMT ship class on the way. Or give it
a list of places and get a distance matrix.

> Early development. Routing, place names, distance matrices and maps work;
> locks, bridges and vessel dimensions are next. See [PLAN.md](PLAN.md).

## Quick start

```sh
uv sync --extra map
uv run dutch-waterways route Volendam Amersfoort --class I --map route.html
```

```
distance:        73.1 km along the fairways
access legs:     1.60 km at origin, 1.71 km at destination (straight line, not included)
smallest class:  II
sections:        25
```

The first run downloads FIS and builds the network into
`~/.cache/dutch-waterways` (about 10 seconds; set `DUTCH_WATERWAYS_CACHE` to
change the location). Places are names (geocoded with OpenStreetMap's
Nominatim, cached) or `LON,LAT`.

Distance matrix, as CSV:

```sh
uv run dutch-waterways od Rotterdam Amsterdam "Den Helder" Lobith --class Va
uv run dutch-waterways od --file places.csv --out matrix.csv   # columns: name[,lon,lat]
```

## From Python

```python
import dutch_waterways as dw

r = dw.route("Volendam", "Amersfoort", min_class="I")
r.length_m, r.smallest_class, r.access_m
r.summary()          # the key figures as a dict
r.sections           # GeoDataFrame of the fairway sections used
r.geometry_wgs84()   # shapely LineString
r.to_map()           # Folium map (pip install 'dutch-waterways[map]')

m = dw.od_matrix(["Rotterdam", "Amsterdam", "Nijmegen"], min_class="IV")  # km
m.attrs["access_km"]
```

Places can also be `(lon, lat)` tuples or shapely Points (pass `crs=`).

### Vessel class and access

`min_class` takes a CEMT class (`"I"`, `"IV"`, `"Va"`, `"VIb"`, ...). Without
it, every fairway counts, including small-craft canals and sections whose class
FIS does not give.

Harbours are often below the class of the fairway they open onto, so a place
may be some way from the nearest fairway of the class asked for. `access`
decides what happens then:

- `access="snap"` (default): the place joins the nearest fairway of the class.
  The straight line to it is reported (`access_m`), not counted.
- `access="network"`: the place joins the nearest fairway of any class, and
  the route uses smaller fairways only where it has to. Their length is
  counted and reported separately (`below_class_m`).

Volendam to Amersfoort for class IV: with `snap`, 85.1 km plus 9 and 10 km of
straight-line access; with `network`, 74.0 km of which 30.4 km (Volendam
harbour and the Eem) is below class IV.

`max_access_m=` makes either mode fail (`TooFarError`) for places further than
that from the network.

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
uv sync --all-extras
uv run pytest              # offline tests
uv run pytest -m online    # end-to-end against live FIS and Nominatim
```

## Licence

Code: [MIT](LICENSE). Network data: Rijkswaterstaat, Fairway Information
Services, CC-0. Geocoding: © OpenStreetMap contributors, via Nominatim.
