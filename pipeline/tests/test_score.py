from twisty.score import DIRT_NAME, TWIST_ANCHOR_M, TWIST_FLOOR_M, twist_scale


def test_twist_scale_bounds():
    assert twist_scale(0) == 0.0
    assert twist_scale(TWIST_FLOOR_M) == 0.0
    assert twist_scale(TWIST_ANCHOR_M) == 10.0
    assert twist_scale(TWIST_ANCHOR_M * 5) == 10.0  # capped


def test_twist_scale_monotonic():
    vals = [twist_scale(x) for x in (300, 1000, 3000, 8000)]
    assert vals == sorted(vals) and len(set(vals)) == 4


def test_dirt_names():
    for n in ("Sand Mine Road", "Ralph E Simmons Memorial State Forest Trail", "North Grade Road",
              "Forest Road 352", "Lime Rock Road", "FS 75", "Fire Road"):
        assert DIRT_NAME.search(n), n
    for n in ("Park Drive", "Southeast Butler Road", "Rock Hill Road", "Graded Avenue"):
        assert not DIRT_NAME.search(n), n
