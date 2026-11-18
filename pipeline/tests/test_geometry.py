import numpy as np

from twisty.geometry import (
    M_PER_DEG_LAT,
    bend_radii,
    bend_weights,
    project,
    resample,
    sections,
)


def _lonlat_from_xy(xy: np.ndarray, lat0: float = 28.0) -> np.ndarray:
    lat = lat0 + xy[:, 1] / M_PER_DEG_LAT
    lon = xy[:, 0] / (111_320.0 * np.cos(np.radians(lat)))
    return np.column_stack([lon, lat])


def test_resample_spacing():
    xy = np.array([[0.0, 0.0], [1000.0, 0.0]])
    ll = _lonlat_from_xy(xy)
    _, out = resample(ll, step=10.0)
    d = np.hypot(*np.diff(out, axis=0).T)
    assert abs(d.mean() - 10.0) < 0.2


def test_circle_radius_recovered():
    r = 60.0
    t = np.linspace(0, np.pi, 400)
    xy = np.column_stack([r * np.cos(t), r * np.sin(t)])
    _, rxy = resample(_lonlat_from_xy(xy))
    radii = bend_radii(rxy)
    finite = radii[np.isfinite(radii)]
    assert abs(np.median(finite) - r) < 3.0


def test_straight_road_scores_zero():
    xy = np.array([[0.0, 0.0], [5000.0, 0.0]])
    assert sections(_lonlat_from_xy(xy)) == []


def test_weights_order():
    w = bend_weights(np.array([20.0, 60.0, 150.0, 300.0, 1000.0, np.inf]))
    assert list(w) == [2.0, 1.4, 1.0, 0.35, 0.0, 0.0]


def test_sine_road_is_one_curvy_section():
    x = np.linspace(0, 3000, 600)
    y = 80 * np.sin(x / 120.0)  # repeating bends
    secs = sections(_lonlat_from_xy(np.column_stack([x, y])))
    assert len(secs) == 1
    assert secs[0].curvy_m > 500  # bends ~180 m radius: corners + sweepers


def test_projection_scale():
    xy = project(np.array([0.0, 0.001]), np.array([28.0, 28.0]))
    assert abs((xy[1, 0] - xy[0, 0]) - 111_320 * np.cos(np.radians(28)) * 0.001) < 1e-6
