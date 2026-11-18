"""Merge ways into roads, cut curvy sections, and score them with neighborhood filters."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import shapely
from scipy.spatial import cKDTree

from .extract import Extract, Road
from .geometry import Section, project, sections

MIN_CURVY_M = 250.0  # raw score floor before context checks

BUILDING_RADIUS_M = 40.0
POINT_RADIUS_M = 12.0  # junctions / driveways / controls on the road itself

# Thresholds per mile. US riders think in miles; the UI does too.
NEIGHBORHOOD_RULES = {
    # Residential streets with any of these are subdivisions, not rides.
    "residential_buildings_per_mi": 25.0,
    "residential_driveways_per_mi": 6.0,
    "residential_junctions_per_mi": 10.0,
    # Any road class this dense is in-town.
    "any_buildings_per_mi": 90.0,
    "any_controls_per_mi": 8.0,
}

M_PER_MI = 1609.344

# Surface: OSM rarely tags it on rural US roads, so missing != unpaved.
UNVERIFIED_SURFACE_MULT = 0.55
DIRT_LINKS_REJECT_PER_MI = 2.0  # tracks / unpaved roads branching off, per mile
DIRT_NAME = re.compile(
    r"\b(trail|grade|mine|fire\s*(road|rd|lane|ln)|forest\s*(road|rd)|tram|logging|jeep|"
    r"sand|clay|dirt|lime\s*rock|limerock|truck\s*trail|fs\s*\d+|fr\s*\d+)\b",
    re.IGNORECASE,
)

# Twist scale: log of context-adjusted curvy meters between a floor and a
# world-class anchor. Fixed, so a 10 means the same thing in every state.
TWIST_FLOOR_M = 150.0
TWIST_ANCHOR_M = 15_000.0  # calibrated against US-129 Tail of the Dragon, see docs


def twist_scale(adjusted_m: float) -> float:
    if adjusted_m <= TWIST_FLOOR_M:
        return 0.0
    t = 10.0 * math.log(adjusted_m / TWIST_FLOOR_M) / math.log(TWIST_ANCHOR_M / TWIST_FLOOR_M)
    return round(min(10.0, t), 1)


@dataclass
class Scored:
    section: Section
    key: str
    name: str | None
    ref: str | None
    highway: str
    maxspeed_mph: float | None
    way_ids: list[int]
    buildings_per_mi: float
    junctions_per_mi: float
    driveways_per_mi: float
    controls_per_mi: float
    dirt_links_per_mi: float
    surface: str  # "likely paved" | "unverified"
    multiplier: float
    reject: str | None
    adjusted: float = 0.0
    twist: float = 0.0


def _group_key(r: Road) -> str:
    if r.ref:
        return f"ref:{r.ref}"
    if r.name:
        return f"name:{r.name}"
    return f"way:{r.way_id}"


def _merged_lines(roads: list[Road]) -> list[np.ndarray]:
    if len(roads) == 1:
        return [roads[0].lonlat]
    merged = shapely.line_merge(shapely.MultiLineString([r.lonlat for r in roads]))
    geoms = merged.geoms if hasattr(merged, "geoms") else [merged]
    return [np.asarray(g.coords) for g in geoms]


def _length_m(r: Road) -> float:
    xy = project(r.lonlat[:, 0], r.lonlat[:, 1])
    return float(np.hypot(*np.diff(xy, axis=0).T).sum())


def _dominant(roads: list[Road]) -> Road:
    return max(roads, key=_length_m)


def _paved_share(roads: list[Road]) -> float:
    lengths = [_length_m(r) for r in roads]
    total = sum(lengths) or 1.0
    return sum(l for r, l in zip(roads, lengths) if r.paved_evidence) / total


class _PointIndex:
    def __init__(self, lonlat: np.ndarray):
        self.n = len(lonlat)
        self.tree = cKDTree(project(lonlat[:, 0], lonlat[:, 1])) if self.n else None

    def count_near(self, xy: np.ndarray, radius: float) -> int:
        if not self.n:
            return 0
        hits = self.tree.query_ball_point(xy, radius, workers=-1)
        return len(set().union(*hits)) if len(hits) else 0


def score(ex: Extract, log=print) -> list[Scored]:
    groups: dict[str, list[Road]] = defaultdict(list)
    for r in ex.roads:
        groups[_group_key(r)].append(r)
    log(f"  {len(ex.roads):,} candidate ways in {len(groups):,} named/ref groups")

    raw: list[tuple[str, list[Road], Section]] = []
    for key, rs in groups.items():
        for line in _merged_lines(rs):
            for sec in sections(line):
                if sec.curvy_m >= MIN_CURVY_M:
                    raw.append((key, rs, sec))
    log(f"  {len(raw):,} sections above raw curvature floor")

    buildings = _PointIndex(ex.building_lonlat)
    junctions = _PointIndex(ex.junction_lonlat)
    driveways = _PointIndex(ex.driveway_lonlat)
    controls = _PointIndex(ex.control_lonlat)
    dirt = _PointIndex(ex.dirt_link_lonlat)
    R = NEIGHBORHOOD_RULES
    group_cache: dict[str, tuple[Road, float]] = {}

    out: list[Scored] = []
    for key, rs, sec in raw:
        if key not in group_cache:
            group_cache[key] = (_dominant(rs), _paved_share(rs))
        dom, paved_share = group_cache[key]
        mi = sec.length_m / M_PER_MI
        b = buildings.count_near(sec.xy, BUILDING_RADIUS_M) / mi
        j = junctions.count_near(sec.xy, POINT_RADIUS_M) / mi
        d = driveways.count_near(sec.xy, POINT_RADIUS_M) / mi
        c = controls.count_near(sec.xy, POINT_RADIUS_M) / mi
        t = dirt.count_near(sec.xy, POINT_RADIUS_M) / mi
        surface = "likely paved" if paved_share >= 0.5 else "unverified"
        label = " ".join(x for x in (dom.name, dom.ref) if x)

        reject = None
        if surface == "unverified":
            if not label:
                reject = "likely unpaved/private: unnamed and untagged"
            elif DIRT_NAME.search(label):
                reject = f"likely unpaved: name '{label}'"
            elif t >= DIRT_LINKS_REJECT_PER_MI:
                reject = f"likely unpaved: {t:.1f} dirt tracks/mi branch off"
        if reject is None and dom.highway == "residential":
            if b > R["residential_buildings_per_mi"]:
                reject = f"subdivision: {b:.0f} buildings/mi"
            elif d > R["residential_driveways_per_mi"]:
                reject = f"subdivision: {d:.0f} driveways/mi"
            elif j > R["residential_junctions_per_mi"]:
                reject = f"subdivision: {j:.0f} intersections/mi"
        if reject is None and b > R["any_buildings_per_mi"]:
            reject = f"in town: {b:.0f} buildings/mi"
        if reject is None and c > R["any_controls_per_mi"]:
            reject = f"in town: {c:.0f} signals/stops per mi"

        m = 1.0
        m /= 1.0 + b / 60.0
        m /= 1.0 + max(0.0, j - 3.0) / 6.0
        m /= 1.0 + c / 3.0
        m /= 1.0 + d / 4.0
        m /= 1.0 + t / 2.0
        if surface == "unverified":
            m *= UNVERIFIED_SURFACE_MULT
        if dom.highway == "residential":
            m *= 0.6
        if dom.maxspeed_mph is not None and dom.maxspeed_mph <= 25:
            m *= 0.5

        out.append(
            Scored(
                section=sec, key=key, name=dom.name, ref=dom.ref, highway=dom.highway,
                maxspeed_mph=dom.maxspeed_mph, way_ids=[r.way_id for r in rs][:20],
                buildings_per_mi=b, junctions_per_mi=j, driveways_per_mi=d,
                controls_per_mi=c, dirt_links_per_mi=t, surface=surface,
                multiplier=m, reject=reject,
                adjusted=sec.curvy_m * m,
                twist=twist_scale(sec.curvy_m * m) if reject is None else 0.0,
            )
        )
    return out
