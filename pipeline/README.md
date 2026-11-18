# Twisty pipeline

Scores OpenStreetMap roads for motorcycle-worthy curvature and filters out subdivisions, in-town roads, and likely-unpaved roads.

## Run

```sh
cd pipeline
uv run pytest -q
curl -LO --output-dir ../data https://download.geofabrik.de/north-america/us/florida-latest.osm.pbf
uv run python -m twisty ../data/florida-latest.osm.pbf ../data/florida
```

Outputs `../data/<prefix>-twisties.geojson` (kept, scored) and `../data/<prefix>-rejected.geojson` (with reasons).

## View

```sh
cd .. && python3 -m http.server 8000 --bind 127.0.0.1
# open http://localhost:8000/pipeline/viewer/  (add ?data=tennessee for other runs)
```

## How scoring works

1. **Curvature:**
   - Ways are merged per route number or name, then resampled every 10 m.
   - Bend radius is measured over a 40 m chord.
   - Time in bends is weighted by radius: <40 m x2, <90 m x1.4, <200 m x1, <400 m x0.35.
   - Sections split on straights of 1.5 km or more. Sections must be at least 1 km long.
2. **Neighborhood / in-town filters:**
   - Building density within 40 m.
   - Intersections, driveways, and signals/stops per mile.
   - Residential streets are held to stricter limits.
3. **Surface:**
   - A section is "likely paved" if most of its length has paving evidence: a paved surface tag, a ref, lanes, maxspeed, or primary class or higher.
   - Otherwise it is "unverified" (x0.55). Unverified sections are rejected if they are unnamed, have a dirt-ish name, or have 2+ dirt tracks branching off per mile.
4. **Twist (0-10):** log scale of context-adjusted curvy meters, from 150 m (0) to 15 km (10). Calibrated on Tennessee:

   | Road | Twist |
   |---|---|
   | US 129 Tail of the Dragon | 10.0 |
   | US 421 "The Snake" | 10.0 |
   | Newfound Gap Rd | 9.8 |
   | Cherohala Skyway | 9.2 |

   Florida's best roads score about 5.

Original implementation; no code from the GPL `curvature` project.
