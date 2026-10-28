import numpy as np
import pandas as pd

from nearmisslens import match


def states(prefix, n=20, dx=0.0):
    rows = []
    for k, (x0, cls) in enumerate([(0, "vehicle"), (10, "two_wheeler")]):
        for f in range(1, n + 1):
            rows.append({"id": f"{prefix}{k}", "frame": f, "x": x0 + f + dx, "y": 0.0, "cls": cls,
                         "vx": 10.0, "vy": 0.0, "speed": 10.0})
    return pd.DataFrame(rows)


def test_tracking_metrics_perfect_and_offset():
    ref, pred = states("r"), states("p", dx=0.3)
    m = match.tracking_metrics(pred, ref, "vehicle")
    assert m["recall"] == 1.0 and m["precision"] == 1.0
    assert abs(m["position_rmse_m"] - 0.3) < 1e-9 and m["id_switches_per_min"] == 0
    far = states("p", dx=5.0)
    assert match.tracking_metrics(far, ref, "vehicle")["recall"] == 0.0


def test_event_metrics():
    ref = states("r")
    pred = states("p")
    pmap = match.id_map(pred, ref)
    rev = pd.DataFrame([{"id_1": "r0", "id_2": "r1", "frame_start": 5, "frame_end": 8}])
    pev = pd.DataFrame([{"id_1": "p0", "id_2": "p1", "frame_start": 9, "frame_end": 12},
                        {"id_1": "p0", "id_2": "p1", "frame_start": 60, "frame_end": 62}])
    e = match.event_metrics(pev, rev, pmap)
    assert e["tp"] == 1 and e["recall"] == 1.0 and e["precision"] == 0.5
