# dutch-waterways

Route planner for Dutch inland waterways, built on Rijkswaterstaat's official
Fairway Information Services (FIS) network (open data, CC-0, no API key).

Give it an origin, a destination and a vessel; get the sailing route along
the marked fairways, its length, the bridges and locks on the way, and the
largest vessel the route takes. Or give it a list of places and get a
distance matrix.

> Early development. Routing, vessel dimensions, place names, distance
> matrices, maps and a browser route planner work. See [PLAN.md](PLAN.md).

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

With vessel dimensions (metres), the route avoids fixed bridges, locks and
fairways the vessel does not fit:

```sh
uv run dutch-waterways route Rotterdam Amsterdam --class Va \
    --length 135 --beam 11.45 --draught 2.6 --air-draught 7
```

```
distance:        101.0 km along the fairways
...
bridges:         32 (1 movable)
locks:           1
  km    51.5  Prinses Beatrixsluizen
route allows:    length 135 m, beam 18 m, draught 2.7 m, air draught 8.7 m
```

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
r.bridges, r.locks   # GeoDataFrames, in order, with at_km
r.limits()           # largest length, beam, draught, air draught the route takes
r.sections           # GeoDataFrame of the fairway sections used
r.geometry_wgs84()   # shapely LineString
r.to_map()           # Folium map (pip install 'dutch-waterways[map]')

m = dw.od_matrix(["Rotterdam", "Amsterdam", "Nijmegen"], min_class="IV")  # km
m.attrs["access_km"]
```

Places can also be `(lon, lat)` tuples or shapely Points (pass `crs=`).

### Vessels

```python
ship = dw.Vessel("Va", length=135, beam=11.45, draught=2.6, air_draught=7)
dw.route("Rotterdam", "Amsterdam", vessel=ship)
dw.od_matrix(["Rotterdam", "Amsterdam", "Nijmegen"], vessel=ship)
```

Every field is optional. A vessel fits a section when it is within the
section's maximum length, beam, draught and air draught, and fits a bridge or
lock when at least one opening or chamber is wide, long and high enough for
it at once. Movable bridges are assumed to open; lift bridges keep their
height when open.

What FIS gives, and what that means for results:

- Unknown is passable. Where FIS gives no limit, none is applied. Maximum
  length and beam are known for about 8,000 km of the 12,900 km network,
  draught for 4,500 km; 3,932 bridges and 383 locks are on routable sections.
- Clearances and draughts are against FIS reference levels, not today's water
  level. River draughts can be low-water figures: the Lek between the
  Lekkanaal and Krimpen allows 2.7 m.
- Lock sill depths are not used: FIS gives them against differing reference
  levels.

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

Sections a vessel's dimensions do not fit are never used, in either mode.
`max_access_m=` makes either mode fail (`TooFarError`) for places further than
that from the network.

## Web map

`web/` is a route planner that runs entirely in the browser: type or click
two places, set the vessel, and see the route, its bridges and locks, and
what it allows. Routes can be shared by URL. The router (`web/router.js`) is
a port of the Python one and is tested against it; there is no server.

To try it locally:

```sh
uv run dutch-waterways export-web          # -> web/data/network.json (about 1 MB)
python3 -m http.server -d web 8000         # then open http://localhost:8000
```

`.github/workflows/pages.yml` builds the data from live FIS and publishes
`web/` to GitHub Pages on each push and monthly. It is off until the
repository variable `PAGES_ENABLED` is `true` and Pages is set to deploy from
GitHub Actions.

Place boxes autocomplete: Dutch places, streets and addresses from
[PDOK's Locatieserver](https://www.pdok.nl/) (Kadaster's open geocoder,
built for search-as-you-type), plus locks and bridges from the network
itself. Map tiles come from openstreetmap.org (fine for light use; see the
[tile usage policy](https://operations.osmfoundation.org/policies/tiles/)).

## The network

`dutch-waterways build` writes `network.parquet`, one row per FIS fairway
section (`vaarwegvak`), in EPSG:28992 (RD New, metres):

| Column | Meaning |
|---|---|
| `section_id` | FIS section id |
| `source`, `target` | FIS junction ids; geometry runs from `source` to `target` |
| `length_m` | geometry length in metres (routing weight) |
| `fis_km` | length as given by FIS |
| `cemt`, `cemt_rank` | CEMT class (`_0` = small craft only) and its rank; empty if unknown |
| `routeid`, `km_begin`, `km_end` | FIS route and kilometre range |
| `is_stub` | placeholder link to a foreign network; never routed |
| `max_length`, `max_beam`, `max_draught`, `max_air_draught` | strictest FIS limit on the section; empty if unknown |

and `network.structures.parquet`, one row per bridge or lock, with the
section it is on, its position along it, whether it opens, and per opening or
chamber its width, length and clearance.

As built on 2026-10-07: 4,740 routable sections, 12,867 km, of which 8,521 km
have a CEMT class. All sections are two-way (`direction = H` throughout).

## Development

```sh
uv sync --all-extras
uv run pytest              # offline tests
uv run pytest -m online    # end-to-end against live FIS and Nominatim

# the browser-router tests need node
```

## Licence

Code: [MIT](LICENSE). Network data: Rijkswaterstaat, Fairway Information
Services, CC-0. Geocoding: © OpenStreetMap contributors, via Nominatim.
