import numpy as np
import pandas as pd
import pytest

from nearmisslens import conflicts as cf


def track(uid, x0, y0, vx, vy, n=40, fps=10, cls="vehicle", length=4.5, width=1.8):
    t = np.arange(n) / fps
    return pd.DataFrame({"id": uid, "frame": np.arange(n) + 1, "t": t, "x": x0 + vx * t, "y": y0 + vy * t,
                         "vx": vx, "vy": vy, "yaw": np.arctan2(vy, vx) if (vx or vy) else 0.0,
                         "length": length, "width": width, "cls": cls})


def test_ttc_rear_end():
    s1 = np.array([[0, 0, 10, 0, 0, 4.5, 1.8]], float)
    s2 = np.array([[12, 0, 1, 0, 0, 4.5, 1.8]], float)
    assert cf.ttc_batch(s1, s2)[0] == pytest.approx(0.9, abs=0.05)
    s3 = np.array([[12, 5, 1, 0, 0, 4.5, 1.8]], float)
    assert np.isinf(cf.ttc_batch(s1, s3)[0])


def test_ttc_events_type_and_severity():
    st = pd.concat([track(1, 0, 0, 10, 0), track(2, 14, 0, 1, 0)])
    ev = cf.ttc_events(st)
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["type"] == "rear_end" and e["min_ttc"] <= 1.5 and e["severity"]


def test_no_conflict_parallel_lanes():
    st = pd.concat([track(1, 0, 0, 10, 0), track(2, 5, 4, 10, 0)])
    assert cf.ttc_events(st).empty


def test_pet_crossing():
    a = track(1, -20, 0, 10, 0, n=50)
    b = track(2, 0, -30, 0, 10, n=50, cls="pedestrian", length=0.6, width=0.6)
    pet = cf.pet_events(pd.concat([a, b]))
    row = pet[(pet.id_1 == 1) & (pet.id_2 == 2)].iloc[0]
    assert 0.3 < row["pet"] < 1.2
    assert {row["cls_1"], row["cls_2"]} == {"vehicle", "pedestrian"}


def test_conflict_type_thresholds():
    assert list(cf.conflict_type(np.array([10, 90, 50]))) == ["rear_end", "crossing", "lane_change"]


def test_pet_ignores_following():
    a = track(1, -20, 0, 10, 0, n=50)
    b = track(2, -32, 0, 10, 0, n=50)
    assert cf.pet_events(pd.concat([a, b])).empty


def test_ttc_ignores_initial_overlap():
    st = pd.concat([track(1, 0, 0, 5, 0), track(2, 1, 0, 1, 0)])
    assert cf.ttc_events(st).empty


def test_footprint_cells_follow_orientation():
    straight = cf._footprint_cells(0.0, 0.0, 0.0, 4.0, 1.0, 0.5)
    diagonal = cf._footprint_cells(0.0, 0.0, np.pi / 4, 4.0, 1.0, 0.5)
    assert len(straight) == 16
    assert len(diagonal) < 30
