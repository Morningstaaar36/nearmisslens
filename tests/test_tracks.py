import numpy as np
import pandas as pd

from nearmisslens.tracks import smooth_states


def pts(frames, vx=10.0, fps=10.0):
    f = np.asarray(frames)
    return pd.DataFrame({"id": "a", "frame": f, "x": vx * f / fps, "y": 0.0, "axis": 0.0, "length": 4.5,
                         "width": 1.8, "cls": "vehicle"})


def test_velocity_from_positions():
    st = smooth_states(pts(range(1, 40)), 10.0)
    assert np.allclose(st["vx"], 10.0, atol=1e-6) and np.allclose(st["vy"], 0.0, atol=1e-6)


def test_gaps_split_or_fill():
    filled = smooth_states(pts(list(range(1, 20)) + list(range(22, 40))), 10.0)
    assert filled["frame"].tolist() == list(range(1, 40))
    split = smooth_states(pts(list(range(1, 20)) + list(range(30, 50))), 10.0)
    assert 25 not in set(split["frame"]) and np.allclose(split["vx"], 10.0, atol=1e-6)
