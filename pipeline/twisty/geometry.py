"""Curvature geometry: projection, resampling, bend radius, and sectioning.

Original implementation of the general idea popularized by roadcurvature.com
(score = length of road spent in bends, weighted by bend tightness). No code
from the GPL-licensed `curvature` project is used.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQ = 111_320.0

STEP_M = 10.0  # resample spacing
CHORD_STEPS = 2  # radius measured over points i-2, i, i+2 (20 m each side)

# (max radius in meters, weight). First match wins; larger radius = gentler bend.
RADIUS_WEIGHTS: tuple[tuple[float, float], ...] = (
    (40.0, 2.0),  # hairpin / tight
    (90.0, 1.4),  # sharp
    (200.0, 1.0),  # proper corner
    (400.0, 0.35),  # sweeper
)

STRAIGHT_SPLIT_M = 1_500.0  # split sections on straight runs at least this long
MIN_SECTION_M = 1_000.0


def project(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Local equirectangular projection to meters. Good enough for short-range distances."""
    x = lon * M_PER_DEG_LON_EQ * np.cos(np.radians(lat))
    y = lat * M_PER_DEG_LAT
    return np.column_stack([x, y])


def resample(lonlat: np.ndarray, step: float = STEP_M) -> tuple[np.ndarray, np.ndarray]:
    """Resample a lon/lat polyline at a fixed spacing. Returns (lonlat, meters)."""
    xy = project(lonlat[:, 0], lonlat[:, 1])
    seg = np.hypot(*np.diff(xy, axis=0).T)
    keep = np.concatenate([[True], seg > 0.01])  # drop duplicate points
    lonlat, xy = lonlat[keep], xy[keep]
    if len(xy) < 2:
        return lonlat, xy
    dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    targets = np.arange(0.0, dist[-1], step)
    if dist[-1] - targets[-1] > step * 0.25:
        targets = np.append(targets, dist[-1])
    out_ll = np.column_stack(
        [np.interp(targets, dist, lonlat[:, 0]), np.interp(targets, dist, lonlat[:, 1])]
    )
    out_xy = np.column_stack(
        [np.interp(targets, dist, xy[:, 0]), np.interp(targets, dist, xy[:, 1])]
    )
    return out_ll, out_xy


def bend_radii(xy: np.ndarray, k: int = CHORD_STEPS) -> np.ndarray:
    """Circumradius at each point using neighbors k steps away. Ends get +inf."""
    n = len(xy)
    radii = np.full(n, np.inf)
    if n < 2 * k + 1:
        return radii
    a, b, c = xy[: n - 2 * k], xy[k : n - k], xy[2 * k :]
    ab = np.hypot(*(b - a).T)
    bc = np.hypot(*(c - b).T)
    ca = np.hypot(*(a - c).T)
    cross = np.abs((b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0])
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(cross > 1e-9, ab * bc * ca / (2.0 * cross), np.inf)
    radii[k : n - k] = r
    return radii


def bend_weights(radii: np.ndarray) -> np.ndarray:
    w = np.zeros_like(radii)
    assigned = np.zeros(len(radii), dtype=bool)
    for max_r, weight in RADIUS_WEIGHTS:
        hit = (radii < max_r) & ~assigned
        w[hit] = weight
        assigned |= hit
    return w


@dataclass
class Section:
    lonlat: np.ndarray  # resampled points
    xy: np.ndarray  # same points in meters
    weights: np.ndarray

    @property
    def length_m(self) -> float:
        return (len(self.xy) - 1) * STEP_M

    @property
    def curvy_m(self) -> float:
        """Weighted meters spent in bends: the raw curvature score."""
        return float(self.weights.sum() * STEP_M)


def sections(lonlat: np.ndarray) -> list[Section]:
    """Split a road into curvy sections separated by long straights."""
    ll, xy = resample(lonlat)
    if len(xy) < 2 * CHORD_STEPS + 1:
        return []
    w = bend_weights(bend_radii(xy))

    straight = w == 0
    min_run = int(STRAIGHT_SPLIT_M / STEP_M)
    # Mark points inside long straight runs as cut points.
    cut = np.zeros(len(w), dtype=bool)
    edges = np.diff(np.concatenate([[0], straight.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    for s, e in zip(starts, ends):
        if e - s >= min_run:
            cut[s:e] = True

    out: list[Section] = []
    edges = np.diff(np.concatenate([[0], (~cut).astype(np.int8), [0]]))
    for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        seg_w = w[s:e]
        nz = np.flatnonzero(seg_w)
        if len(nz) == 0:
            continue
        s2, e2 = s + nz[0], s + nz[-1] + 1  # trim straight ends
        sec = Section(ll[s2:e2], xy[s2:e2], w[s2:e2])
        if sec.length_m >= MIN_SECTION_M:
            out.append(sec)
    return out
