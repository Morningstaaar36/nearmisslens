import numpy as np
import pandas as pd

from nearmisslens import movements as mv


def path(uid, points, cls="vehicle", fps=10, speed=8.0):
    pts = np.asarray(points, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.arange(0, s[-1] / speed, 1 / fps)
    x = np.interp(t * speed, s, pts[:, 0])
    y = np.interp(t * speed, s, pts[:, 1])
    vx, vy = np.gradient(x, 1 / fps), np.gradient(y, 1 / fps)
    return pd.DataFrame({"id": uid, "t": t, "x": x, "y": y, "vx": vx, "vy": vy, "cls": cls})


def test_movement_from_arms_right_hand_traffic():
    assert mv.movement("N", "E") == "left" and mv.movement("N", "W") == "right"
    assert mv.movement("S", "N") == "through" and mv.movement("E", "E") == "u_turn"
    assert mv.movement("unknown", "E") == "unknown"


def test_routes_and_entry_signal():
    st = pd.concat([path(1, [(0, 40), (0, 0), (40, 0)]),
                    path(2, [(-40, 0), (40, 0)]),
                    path(3, [(0, -40), (0, 40)])])
    r = mv.routes(st, centre=(0.0, 0.0)).set_index("id")
    assert r.loc[1, "entry_arm"] == "N" and r.loc[1, "exit_arm"] == "E" and r.loc[1, "movement"] == "left"
    assert r.loc[2, "movement"] == "through" and r.loc[3, "entry_arm"] == "S"
    assert abs(r.loc[2, "t_entry"] - 2.5) < 0.2
    signals = pd.DataFrame({"direction": ["W", "W"], "turn": ["s", "s"], "begin_time": [0, 2],
                            "end_time": [2, 10], "state": ["G", "r"]})
    rows = r.reset_index()
    assert mv.entry_signal(signals, rows[rows["id"] == 2].iloc[0]) == "r"
    assert mv.entry_signal(signals, rows[rows["id"] == 1].iloc[0]) is None
    labels = pd.Series({1: "N-E", 2: "W-E", 3: "S-Unknown"})
    acc = mv.route_accuracy(st, labels)
    assert acc["tracks"] == 2 and acc["route_accuracy"] == 1.0


def test_queued_vehicle_enters_when_it_moves():
    wait = pd.DataFrame({"id": 1, "t": np.arange(0, 5, 0.1), "x": -15.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "cls": "vehicle"})
    go = path(1, [(-15, 0), (40, 0)]).assign(t=lambda d: d["t"] + 5.0)
    st = pd.concat([path(1, [(-40, 0), (-15, 0)]).assign(t=lambda d: d["t"] - 3.2), wait, go])
    r = mv.routes(st, centre=(0.0, 0.0))
    assert r.loc[0, "t_entry"] >= 5.0
