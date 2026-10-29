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


def _line(tid, f0, f1, x0, vx, y=0.0, cls="two_wheeler"):
    import numpy as np
    import pandas as pd
    f = np.arange(f0, f1)
    return pd.DataFrame({"id": tid, "frame": f, "x": x0 + vx * (f - f0) / 10, "y": y, "cls": cls})


def test_stitch_joins_a_broken_track_but_not_a_neighbour():
    import pandas as pd
    from nearmisslens.tracks import stitch
    a = _line("a", 0, 30, 0.0, 5.0)
    b = _line("b", 35, 60, 17.5, 5.0)
    other = _line("c", 35, 60, 17.5, 5.0, y=6.0)
    car = _line("d", 35, 60, 17.5, 5.0, cls="vehicle")
    out = stitch(pd.concat([a, b, other, car]), fps=10)
    ids = out.groupby("frame")["id"].apply(set)
    assert out.loc[out["frame"] == 40, "id"].tolist().count("a") == 1
    assert set(out["id"]) == {"a", "c", "d"} and ids.loc[40] == {"a", "c", "d"}


def test_stitch_chains_fragments_and_respects_the_gap():
    import pandas as pd
    from nearmisslens.tracks import stitch
    parts = [_line("a", 0, 20, 0.0, 4.0), _line("b", 25, 45, 10.0, 4.0), _line("c", 48, 70, 19.2, 4.0)]
    assert set(stitch(pd.concat(parts), fps=10)["id"]) == {"a"}
    late = [_line("a", 0, 20, 0.0, 4.0), _line("b", 40, 60, 16.0, 4.0)]
    assert set(stitch(pd.concat(late), fps=10, max_gap_s=1.0)["id"]) == {"a", "b"}
