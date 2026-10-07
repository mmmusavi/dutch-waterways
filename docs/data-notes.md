# Notes on the FIS data

How dutch-waterways reads Rijkswaterstaat's Fairway Information Services
(FIS), and what the data does and does not say. Figures are from the build of
2026-10-07.

## Source

All layers are open data (CC-0) from one ArcGIS REST service, no key needed:

`https://geo.rijkswaterstaat.nl/arcgis/rest/services/GDR/fis_vnds/MapServer`

Each layer is queried as `/<layer>/query?where=1=1&outFields=*&f=geojson`,
paged with `resultOffset` / `resultRecordCount=1000` until
`exceededTransferLimit` is false. Geometry comes back in WGS84 and is
reprojected to EPSG:28992 (RD New) for metres.

| Layer | Name | Used for |
|---|---|---|
| 58 | `vaarwegvak` | the routable network: `startjunctionid`, `endjunctionid`, `length` (km), `routeid`, `routekmbegin` / `routekmend` |
| 49 | `scheeepvaartklasse` (sic) | CEMT class per `routeid` and km range; `code` in `_0, I, II, III, IV, V_A, V_B, VI_A, VI_B, VI_C` |
| 24 | `vaarwegjunctie` | junction points, to orient section geometry |
| 64 / 65 | `sluis_v` / `sluiskolk_v` | Dutch locks and their chambers |
| 3 / 15 | `brug` / `opening` | bridges and their openings |
| 37 | `max_toegestane_afmeting` | legal maximum length, width, draught and height |
| 200 | `maximale dimensies visuris` | VisuRIS maximum length and width, wider coverage |
| 54 | `vaarwegdiepte` | fairway depth (downloaded, not used yet) |
| 197 | `routeplanning` | Rijkswaterstaat's route-planning lines (not used yet) |

## Sections

- 5,078 sections. 338 of them are links to foreign networks: an empty km
  range, `length` 0.103, `foreigncode` AT / BE / DE / FR, and a straight
  placeholder line that can be hundreds of km long. They are kept as
  `is_stub` and never routed.
- The other 4,740 sections (12,867 km) form one connected network.
- `direction` is `H` on every section: the network is two-way throughout.
- `length` is in km and matches the RD geometry length within 0.4 % for 90 %
  of sections; routing uses the geometry length.
- Geometry runs from the start to the end junction for all but 2 sections;
  the build reverses those.
- Section `name`s are generic ("Vaarwegvak van 5 tot 9").

## Ship classes

Class records line up with section km ranges: every section that overlaps a
class record overlaps exactly one, completely. The build gives each section
the class of the record that overlaps it most (the smaller class on a tie).

4,315 sections (8,521 km) get a class; 425 routable sections (about
4,350 km) have none. Sections without a class are used only when no class is
asked for.

## Dimension limits

Each section gets the strictest maximum length, width (beam), draught and
height from layers 37 and 200 among the records that overlap it. Coverage:
length and beam on about 8,000 km, draught on about 4,500 km, height on
about 580 km. A limit FIS does not give is not applied.

Draughts on rivers can be low-water figures: the Lek between the Lekkanaal
and Krimpen (route 55181, km 80.8–120.4) allows 2.7 m, against 4.0 m
upstream.

## Bridges

Bridges are built from `opening` records grouped by their parent (a bridge, or
another structure such as an aqueduct), one structure per parent and section.
Each opening keeps its width and clearance. Fixed openings (`VST`, `OKW`)
keep their closed clearance; other types (lift, bascule, swing, vertical lift,
...) are assumed to open, with no height limit unless FIS gives an open
clearance. Openings that are ruined or only planned are left out.

A vessel fits a bridge when one opening is wide and high enough for it at
once. 3,932 bridges lie on routable sections; bridges without opening
records are listed but never block.

## Locks

Layers 19 and 20 (`sluis` / `sluiskolk` points) hold foreign locks only. The
Dutch locks are the polygon layers 64 (383 locks) and 65 (428 chambers). A
chamber's usable length is the shortest of its length and lockage lengths; its
width is the narrower of chamber and gate.

Sill depths are given against differing reference levels (97 of 428 are
positive), so they are not compared with draught.

## Places

Locks and bridges carry FIS's `city` for 96 % of them; the web map uses it
to tell apart locks with the same name.

## Why FIS

Volendam to Amersfoort, measured 2026-10-07:

| Network | Distance | Notes |
|---|---|---|
| FIS, all fairways | 66.4 km | through Almere's inner-city canals (class 0) |
| FIS, class I and up | 73.0 km | Markermeer, IJmeer, Gooimeer, Eemmeer, Eem; smallest class II |
| FIS, class IV, `access="network"` | 74.0 km | 30.4 km of it below class IV (Volendam harbour, the Eem) |
| OpenStreetMap, straight lines across lakes | 53.8 km | too short: no fairway lines across the big lakes |
| `searoute` / `scgraph` | — | sea networks, unusable inland |
| OSRM, by road | 67.8 km | for comparison |

OpenStreetMap's waterway tags also do not say what is navigable, or for
which ship class.

NWB-Vaarwegen through PDOK's OGC API
(`https://api.pdok.nl/rws/nationaal-wegenbestand-vaarwegen/ogc/v1`,
collection `vaarwegvakken`) is topological too (`vwj_id_beg`, `vwj_id_end`)
and gives the same 66.4 km, but has no ship class.

## References

- FIS navigability dataset: https://data.overheid.nl/en/dataset/64442-fis-vnds---navigability---lijnen
- NWB-Vaarwegen: https://www.pdok.nl/introductie/-/article/nationaal-wegen-bestand-nwb-vaarwegen
- Deltares digitaltwin-waterway: https://github.com/Deltares/digitaltwin-waterway
- Topological FIS network (Zenodo, doi:10.5281/zenodo.4578289): https://search.fid-benelux.de/Record/base-26662079
- OpenTNSim (TU Delft): https://opentnsim.readthedocs.io/
