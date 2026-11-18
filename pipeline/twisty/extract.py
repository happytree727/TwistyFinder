"""Single pass over an OSM PBF: candidate roads plus the context signals used to
filter out neighborhoods (buildings, intersections, driveways, traffic controls)."""

from __future__ import annotations

import re
import time
from array import array
from dataclasses import dataclass, field

import numpy as np
import osmium

# Roads we score. Motorways are excluded (never twisty, not the point).
CANDIDATE_HIGHWAYS = {
    "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
}
# Everything a car can drive on: used for intersection degree.
DRIVABLE_HIGHWAYS = CANDIDATE_HIGHWAYS | {
    "motorway", "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link", "living_street", "service", "road",
}
UNPAVED = {
    "unpaved", "gravel", "fine_gravel", "compacted", "dirt", "earth", "ground",
    "grass", "sand", "mud", "pebblestone", "rock", "shells", "woodchips", "grass_paver",
}
PAVED = {"paved", "asphalt", "concrete", "concrete:plates", "concrete:lanes", "chipseal", "paving_stones"}
BLOCKED_ACCESS = {"private", "no", "customers", "agricultural", "forestry", "delivery"}
# Higher classes are effectively always paved in the US.
PAVED_CLASSES = {"trunk", "primary", "secondary"}
CONTROL_HIGHWAY_NODES = {"traffic_signals", "stop", "give_way", "crossing", "mini_roundabout"}

_num = re.compile(r"(\d+(?:\.\d+)?)")


def parse_mph(v: str | None) -> float | None:
    if not v:
        return None
    m = _num.search(v)
    if not m:
        return None
    n = float(m.group(1))
    return n if "mph" in v else n / 1.609


@dataclass
class Road:
    way_id: int
    name: str | None
    ref: str | None
    highway: str
    maxspeed_mph: float | None
    refs: np.ndarray  # node ids
    lonlat: np.ndarray  # (n, 2)
    paved_evidence: bool  # explicit surface, route number, lanes, speed limit, or major class


def paved_evidence(tags) -> bool:
    if tags.get("surface") in PAVED:
        return True
    if tags.get("highway") in PAVED_CLASSES:
        return True
    return any(k in tags for k in ("ref", "lanes", "maxspeed"))


@dataclass
class Extract:
    roads: list[Road] = field(default_factory=list)
    building_lonlat: np.ndarray | None = None
    control_lonlat: np.ndarray | None = None
    junction_lonlat: np.ndarray | None = None
    driveway_lonlat: np.ndarray | None = None
    dirt_link_lonlat: np.ndarray | None = None  # where tracks / unpaved roads join candidates


def _is_candidate(tags) -> bool:
    if tags.get("highway") not in CANDIDATE_HIGHWAYS:
        return False
    if tags.get("area") == "yes" or tags.get("junction") in ("roundabout", "circular"):
        return False
    if tags.get("access") in BLOCKED_ACCESS or tags.get("motor_vehicle") in BLOCKED_ACCESS:
        return False
    if tags.get("surface") in UNPAVED:
        return False
    return True


def run(pbf_path: str, log=print) -> Extract:
    t0 = time.time()
    roads: list[Road] = []
    bld = array("d")
    ctl = array("d")
    # Way-incidence counts for intersection degree: interior nodes count twice, ends once.
    incid = array("q")
    driveway_refs = array("q")
    dirt_refs = array("q")

    fp = (
        osmium.FileProcessor(pbf_path)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("highway", "building", "traffic_calming", "crossing"))
    )
    n_bad = 0
    for i, o in enumerate(fp):
        if i and i % 2_000_000 == 0:
            log(f"  {i:,} objects, {len(roads):,} roads, {len(bld)//2:,} buildings, {time.time()-t0:.0f}s")
        if o.is_node():
            t = o.tags
            if t.get("highway") in CONTROL_HIGHWAY_NODES or "traffic_calming" in t or "crossing" in t:
                ctl.append(o.location.lon)
                ctl.append(o.location.lat)
            continue
        if not o.is_way():
            continue
        t = o.tags
        if "building" in t and t.get("building") != "no":
            xs = ys = 0.0
            k = 0
            for n in o.nodes:
                if n.location.valid():
                    xs += n.location.lon
                    ys += n.location.lat
                    k += 1
            if k:
                bld.append(xs / k)
                bld.append(ys / k)
            continue

        hw = t.get("highway")
        if hw == "track" or (hw in DRIVABLE_HIGHWAYS and t.get("surface") in UNPAVED):
            dirt_refs.extend(n.ref for n in o.nodes)
        if hw not in DRIVABLE_HIGHWAYS:
            continue
        refs = [n.ref for n in o.nodes]
        if len(refs) < 2:
            continue
        incid.append(refs[0])
        incid.append(refs[-1])
        for r in refs[1:-1]:
            incid.append(r)
            incid.append(r)
        if hw == "service" and t.get("service") == "driveway":
            driveway_refs.extend(refs)
            continue
        if not _is_candidate(t):
            continue
        try:
            ll = np.array([(n.location.lon, n.location.lat) for n in o.nodes], dtype=float)
        except osmium.InvalidLocationError:
            n_bad += 1
            continue
        roads.append(
            Road(
                way_id=o.id,
                name=t.get("name"),
                ref=t.get("ref"),
                highway=hw,
                maxspeed_mph=parse_mph(t.get("maxspeed")),
                refs=np.array(refs, dtype=np.int64),
                lonlat=ll,
                paved_evidence=paved_evidence(t),
            )
        )

    log(f"  read done in {time.time()-t0:.0f}s ({n_bad} ways with missing locations)")

    # Intersections: nodes with degree >= 3 that lie on candidate roads.
    ids, counts = np.unique(np.frombuffer(incid, dtype=np.int64), return_counts=True)
    junction_ids = ids[counts >= 3]
    drive_ids = np.unique(np.frombuffer(driveway_refs, dtype=np.int64))
    all_refs = np.concatenate([r.refs for r in roads])
    all_ll = np.concatenate([r.lonlat for r in roads])
    j_mask = np.isin(all_refs, junction_ids)
    d_mask = np.isin(all_refs, drive_ids)
    dirt_ids = np.unique(np.frombuffer(dirt_refs, dtype=np.int64))
    t_mask = np.isin(all_refs, dirt_ids)
    # Deduplicate by node id.
    _, j_first = np.unique(all_refs[j_mask], return_index=True)
    _, d_first = np.unique(all_refs[d_mask], return_index=True)
    _, t_first = np.unique(all_refs[t_mask], return_index=True)

    return Extract(
        roads=roads,
        building_lonlat=np.frombuffer(bld, dtype=float).reshape(-1, 2),
        control_lonlat=np.frombuffer(ctl, dtype=float).reshape(-1, 2),
        junction_lonlat=all_ll[j_mask][j_first],
        driveway_lonlat=all_ll[d_mask][d_first],
        dirt_link_lonlat=all_ll[t_mask][t_first],
    )
