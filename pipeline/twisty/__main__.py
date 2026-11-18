"""Usage: uv run python -m twisty <input.osm.pbf> <output-prefix>

Writes <prefix>-twisties.geojson (kept, ranked) and <prefix>-rejected.geojson
(sections filtered as neighborhoods / in-town, with the reason).
"""

from __future__ import annotations

import json
import sys
import time

from . import extract, score

M_PER_MI = 1609.344


def feature(s: score.Scored) -> dict:
    coords = [[round(x, 6), round(y, 6)] for x, y in s.section.lonlat[::2]]
    if len(s.section.lonlat) % 2 == 0:
        coords.append([round(float(v), 6) for v in s.section.lonlat[-1]])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "name": s.name,
            "ref": s.ref,
            "highway": s.highway,
            "twist": s.twist,
            "length_mi": round(s.section.length_m / M_PER_MI, 2),
            "curvy_mi": round(s.section.curvy_m / M_PER_MI, 2),
            "adjusted": round(s.adjusted),
            "multiplier": round(s.multiplier, 3),
            "buildings_per_mi": round(s.buildings_per_mi, 1),
            "junctions_per_mi": round(s.junctions_per_mi, 1),
            "driveways_per_mi": round(s.driveways_per_mi, 1),
            "controls_per_mi": round(s.controls_per_mi, 1),
            "dirt_links_per_mi": round(s.dirt_links_per_mi, 1),
            "surface": s.surface,
            "maxspeed_mph": s.maxspeed_mph,
            "reject": s.reject,
            "osm_way_ids": s.way_ids,
        },
    }


def write(path: str, items: list[score.Scored]) -> None:
    fc = {
        "type": "FeatureCollection",
        "attribution": "(c) OpenStreetMap contributors, ODbL",
        "features": [feature(s) for s in items],
    }
    with open(path, "w") as f:
        json.dump(fc, f, separators=(",", ":"))


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pbf, prefix = sys.argv[1], sys.argv[2]
    t0 = time.time()
    print(f"[1/3] reading {pbf}")
    ex = extract.run(pbf)
    print(
        f"  roads={len(ex.roads):,} buildings={len(ex.building_lonlat):,} "
        f"junctions={len(ex.junction_lonlat):,} driveways={len(ex.driveway_lonlat):,} "
        f"controls={len(ex.control_lonlat):,} dirt_links={len(ex.dirt_link_lonlat):,}"
    )
    print("[2/3] sectioning + scoring")
    scored = score.score(ex)
    kept = sorted((s for s in scored if s.reject is None), key=lambda s: -s.adjusted)
    rejected = [s for s in scored if s.reject is not None]
    print(f"[3/3] writing {len(kept):,} kept, {len(rejected):,} rejected")
    write(f"{prefix}-twisties.geojson", kept)
    write(f"{prefix}-rejected.geojson", rejected)
    print(f"done in {time.time()-t0:.0f}s\n\nTop 25:")
    for s in kept[:25]:
        label = " / ".join(x for x in (s.ref, s.name) if x) or f"way {s.way_ids[0]}"
        print(
            f"  {s.twist:4.1f}  {label[:48]:48s} {s.highway:12s} "
            f"{s.section.length_m/M_PER_MI:5.1f} mi  curvy {s.section.curvy_m/M_PER_MI:4.1f}  "
            f"x{s.multiplier:.2f}  {s.surface:12s} @ {s.section.lonlat[0][1]:.4f},{s.section.lonlat[0][0]:.4f}"
        )


if __name__ == "__main__":
    main()
