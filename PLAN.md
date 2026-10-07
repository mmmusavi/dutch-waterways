# dutch-waterways — project plan

An open-source route planner for Dutch inland waterways: give it an origin and a
destination, get the sailing route, its length, and what is on the way (locks,
bridges, the smallest ship class), on a map and from Python.

Built on Rijkswaterstaat's official Fairway Information Services (FIS) network,
which is open data (CC-0) and needs no API key.

## Why

- There is no open-source "Google Maps for waterways". NavShip and Waterkaarten
  (Water Map Live) do route planning but are closed. Deltares'
  [digitaltwin-waterway](https://github.com/Deltares/digitaltwin-waterway) uses
  FIS, but it is a simulation tool: its `/find_route` endpoint takes FIS junction
  IDs, not places, and its published network covers only the Rhine corridor.
- Researchers need waterway distance matrices (origin-destination). Today they
  fall back on straight-line distance times a factor, or on sea-routing libraries
  (`searoute`, `scgraph`) that do not cover Dutch inland waterways at all.

## What we already know works (prototype, 2026-10-07)

`prototype/fis_dl.py` downloads two FIS layers for a bounding box;
`prototype/fis_route.py` joins them, builds a `networkx` graph and routes.

Test case Volendam -> Amersfoort:

| Network / filter | Distance | Route |
|---|---|---|
| All FIS fairways | 66.4 km | through Almere's inner city canals (CEMT class 0, small craft) |
| CEMT class I and up | **73.0 km** | Markermeer -> IJmeer -> Hollandse Brug -> Gooimeer -> Eemmeer -> Eem; smallest class II |
| CEMT class IV and up | no route | part of the route, likely the Eem, is below class IV |
| OpenStreetMap + straight lines across lakes | 53.8 km | too short: sails straight instead of along the marked fairways |
| `searoute` / `scgraph` (sea networks) | 0 km / straight line | unusable inland |
| OSRM road, for comparison | 67.8 km | |

Lessons from the prototype:

- **Filter by ship class.** Without it, routes take small recreational canals.
- **Snapping matters.** On the commercial network Volendam's nearest point is
  1.4 km away (its harbour is class 0). That access leg is not counted yet.
- OSM is the wrong base: it has no fairway lines across the big lakes, and its
  waterway tags do not say what is navigable.

## Progress

**Milestone 1 done (2026-10-07).** `src/dutch_waterways/`: `fis.py` (paged
download, all layers), `build.py` (class join, orientation, GeoParquet +
summary), `network.py` (snapping, `route()`), `cli.py`. 43 offline tests plus
2 online tests that reproduce Volendam -> Amersfoort (73.0 km class I+,
66.4 km all fairways) from a fresh download.

What the full-country data showed:

- 5,078 sections; 338 are **foreign stubs** (zero km range, `length` = 0.103,
  placeholder geometry up to hundreds of km, `foreigncode` AT/BE/DE/FR...).
  They are flagged `is_stub` and never routed.
- The 4,740 real sections form **one connected component** (12,867 km).
- `direction` is `H` on every section: the network is two-way throughout.
- Class records line up exactly with section km ranges: every section that
  overlaps a record overlaps exactly one, with full coverage. 4,315 sections
  get a class (8,521 km); 425 routable sections (~4,350 km) have none.
- `length` is in km and matches the RD geometry length within 0.4% for 90%
  of sections. Geometry runs start -> end junction for all but 2 sections
  (the build flips those).
- Section `name`s are generic ("Vaarwegvak van 5 tot 9"); fairway names
  will need another layer.
- Snapping is now the main open issue: Volendam -> Amersfoort for class IV
  finds 85.1 km, but with 8.9 km and 10.1 km straight-line access legs.

**Milestone 2 done (2026-10-07).** Place names (Nominatim, rate-limited,
cached on disk), `od_matrix`, Folium maps, top-level `dw.route()` /
`dw.od_matrix()` on a network cached in `~/.cache/dutch-waterways` and built
on first use, CLI `route` / `od` with names. Snapping got two modes:
`access="snap"` (straight-line access leg, reported) and `access="network"`
(sails smaller fairways where it must, at a 1000x cost, and reports them as
`below_class_m`). Class IV Volendam -> Amersfoort: 74.0 km, 30.4 km of it
below class IV. 61 offline + 4 online tests.

Still open from milestone 2: the network is built locally on first use
rather than downloaded as a release asset (the repo is private for now);
section names are generic, so routes cannot yet list the waterways they use.

**Milestone 3 done (2026-10-07).** `Vessel(cemt, length, beam, draught,
air_draught)`; `structures.py` builds bridges (from `opening` records grouped
by parent) and locks (from `sluiskolk_v` chambers grouped by `sluis_v`) with
per-passage width / length / clearance; `join_limits` gives each section the
strictest of layer 37 (legal max dimensions) and layer 200 (VisuRIS).
Routes list bridges and locks in order and report `limits()`. CLI
`--length --beam --draught --air-draught`; maps mark structures. Cached
builds carry a format number and are rebuilt when outdated. 78 offline +
5 online tests. Rotterdam -> Amsterdam for 135 x 11.45 m now takes the
Prinses Beatrixsluizen and the Amsterdam-Rijnkanaal (101.0 km).

Data findings:

- Layers 19 / 20 (`sluis` / `sluiskolk` points) hold foreign locks only.
  Dutch locks are the polygon layers 64 `sluis_v` (383) and 65
  `sluiskolk_v` (428 chambers: length, gate width, sill depth).
- Sill depths use differing reference levels (97 of 428 positive), so they
  are not used for draught.
- Layer 37 draughts on rivers are conservative: the Lek between the
  Lekkanaal and Krimpen (route 55181, km 80.8-120.4) allows 2.7 m.
- Coverage: max length / beam on ~8,000 km, draught on ~4,500 km, air
  draught (section level) on ~580 km; bridges carry the rest of the
  height limits. Unknown limits do not block.

**Milestone 4 done (2026-10-07).** `web/`: static page (MapLibre 5.24 on
OSM raster tiles, proj4 for RD <-> WGS84), `router.js` (a port of the
Python router: snapping on a 2 km grid, both access modes, vessel checks,
Dijkstra), place search through Nominatim, map clicks and draggable
markers, shareable URL hash, fairways coloured by class, bridges and locks
with popups, mobile layout. `dutch-waterways export-web` writes the
network as 1.1 MB JSON (376 KB gzipped; RD metres, 5 m simplification,
full-resolution lengths). Parity: on 200 random real routes the JS and
Python routers agree within 0.05 % on length, with identical structure
lists and errors; pytest runs the JS router through node. Pages workflow
is in place but off (`vars.PAGES_ENABLED`) while the repo is private.

**Milestone 5 done (2026-10-07).** Repository public at
github.com/mmmusavi/dutch-waterways (history rewritten to the GitHub noreply
email first). Web map on GitHub Pages: mmmusavi.github.io/dutch-waterways,
rebuilt from live FIS on each push and monthly. 0.1.0 on PyPI through
Trusted Publishing (`release.yml`, environment `pypi`). Zenodo archive:
concept DOI 10.5281/zenodo.23212583, v0.1.0 DOI 10.5281/zenodo.23212584,
linked to ORCID 0009-0006-6995-7996. To release again: bump the version in
`pyproject.toml` and `CITATION.cff`, then `gh release create vX.Y.Z`.

## Data sources

All CC-0, from Rijkswaterstaat.

**FIS ArcGIS REST service:**
`https://geo.rijkswaterstaat.nl/arcgis/rest/services/GDR/fis_vnds/MapServer`

Query pattern: `/<layer>/query?where=1=1&outFields=*&f=geojson`, with
`resultOffset` / `resultRecordCount=1000` paging until `exceededTransferLimit` is
false. A `geometry=<envelope>` filter limits the query to an area. Geometry
comes back in WGS84; reproject to EPSG:28992 (RD New) for metres.

| Layer id | Name | Use |
|---|---|---|
| 58 | `vaarwegvak` | **the routable network**: `startjunctionid`, `endjunctionid`, `length` (km), `routeid`, `routekmbegin/end`, `direction` |
| 49 | `scheeepvaartklasse` (sic, three e's) | CEMT class per `routeid` + km range; `code` in `_0, I, II, III, IV, V_A, V_B, VI_A, VI_B, ...` |
| 24 | `vaarwegjunctie` | junction points |
| 64 / 65 | `sluis_v` / `sluiskolk_v` | Dutch locks / lock chambers (19 / 20 hold foreign locks only) |
| 3 / 15 | `brug` / `opening` | bridges / bridge openings (clearance) |
| 37 | `max_toegestane_afmeting` | maximum permitted vessel dimensions |
| 200 | `maximale dimensies visuris` | VisuRIS max length / width, wider coverage |
| 54 | `vaarwegdiepte` | fairway depth |
| 197 | `routeplanning` | Rijkswaterstaat's own route-planning lines; worth investigating |

The join used in the prototype: a section gets the class of the
`scheeepvaartklasse` record on the same `routeid` whose km range contains the
section's km midpoint (461 of 505 sections in the test area matched).

**Alternative:** NWB-Vaarwegen through PDOK's OGC API
(`https://api.pdok.nl/rws/nationaal-wegenbestand-vaarwegen/ogc/v1`, collection
`vaarwegvakken`). It is also topological (`vwj_id_beg`, `vwj_id_end`) but has no
ship class, and gave the same 66.4 km.

## Architecture

Three parts. Each one is useful on its own.

1. **Data pipeline.** A script, and later a monthly GitHub Action, downloads FIS
   for the whole country, joins classes and constraints, and publishes a clean
   graph (GeoParquet and/or JSON) as a release asset. The cleaned network is
   itself a useful dataset.
2. **Python library** (`pip install dutch-waterways`, import `dutch_waterways`).
   - `route(origin, destination, vessel=...)` -> length, geometry, locks, bridges,
     smallest class.
   - `od_matrix(places, vessel=...)` -> distance matrix (DataFrame / CSV).
   - Origins and destinations can be coordinates or place names (geocoded with
     Nominatim), snapped to the network, with the access leg reported separately.
   - Vessel constraints: CEMT class, then draught, air draught and beam once the
     bridge, lock and dimension layers are joined.
   - Optional `route.to_map()` with Folium.
3. **Web map.** MapLibre or Leaflet on OpenStreetMap tiles. Click or type an
   origin and destination; see the route, its distance and the locks and bridges
   on it. The whole network can ship to the browser and be routed in JavaScript,
   so the site can run on GitHub Pages with no server.

## Milestones (rough, assuming Claude writes most of the code)

1. Full-country download + graph build + class join, with tests. A few days.
2. Library: `route`, `od_matrix`, snapping, place names, Folium map, docs. A few days.
3. Vessel constraints (bridges, locks, depth, dimensions). A few days.
4. Web map. One to two weeks.
5. Release: PyPI, GitHub Pages, scheduled data refresh, a citable Zenodo DOI.

## Known challenges

- Snapping places to the network (harbour entrances; harbours below the class
  requested).
- Travel *time* needs lock operating hours and waiting times, which FIS does not
  give; distance is the safe first target.
- Directional or one-way sections: check the `direction` field.
- Europe later means joining German (ELWIS/WSV) and Belgian data across borders,
  in different formats.

## Open decisions (for the user)

- Order: library first and then the map (recommended), or the map from the start?
- Coverage: the Netherlands only (recommended to start), or design for Europe now?
- ~~Code licence~~: MIT (decided 2026-10-07); the data stays CC-0 with attribution.
- ~~GitHub account~~: `mmmusavi/dutch-waterways`.

## References

- FIS navigability dataset: https://data.overheid.nl/en/dataset/64442-fis-vnds---navigability---lijnen
- NWB-Vaarwegen: https://www.pdok.nl/introductie/-/article/nationaal-wegen-bestand-nwb-vaarwegen
- Deltares digitaltwin-waterway: https://github.com/Deltares/digitaltwin-waterway
- Topological FIS network (Zenodo, DOI 10.5281/zenodo.4578289): https://search.fid-benelux.de/Record/base-26662079
- OpenTNSim (TU Delft): https://opentnsim.readthedocs.io/
