# Roadmap

## Why this project

- There is no open-source "Google Maps for waterways". NavShip and Waterkaarten
  (Water Map Live) plan routes but are closed. Deltares'
  [digitaltwin-waterway](https://github.com/Deltares/digitaltwin-waterway) uses
  FIS, but as a simulation tool: its `/find_route` endpoint takes FIS junction
  ids rather than places, and its published network covers only the Rhine
  corridor.
- Researchers need waterway distance matrices. Without one they fall back on
  straight-line distance times a factor, or on sea-routing libraries
  (`searoute`, `scgraph`) that do not cover Dutch inland waterways.

## What is there (0.1)

- **Data pipeline:** downloads FIS for the whole country, joins ship classes,
  dimension limits, bridges and locks, and writes a clean GeoParquet network.
  Rebuilt monthly for the web map.
- **Python library and command line:** routes between places, coordinates or
  points; CEMT class and vessel dimensions; bridges and locks on the way;
  distance matrices; Folium maps.
- **Web map:** a browser route planner on GitHub Pages, with no server. Its
  router is a port of the Python one and is tested against it.

How the FIS data is read, and what it does and does not say, is in
[docs/data-notes.md](docs/data-notes.md).

## Next

- **Waterway names on routes.** FIS section names are generic ("Vaarwegvak van
  5 tot 9"); a route should say "Lek, Lekkanaal, Amsterdam-Rijnkanaal".
- **The network as a dataset.** Publish the built network as a release asset,
  so the library can download it instead of building it, and so it can be
  cited and used on its own.
- **Fairway depth.** Layer 54 (`vaarwegdiepte`) is downloaded but not used yet.
- **Rijkswaterstaat's own route lines.** Layer 197 (`routeplanning`) may help
  with names and with checking routes.
- **Travel time.** Needs speeds, lock operating hours and waiting times, which
  FIS does not give; distance stays the reliable output until then.
- **Beyond the Netherlands.** Joining German (ELWIS / WSV) and Belgian data
  across the border, in different formats.
