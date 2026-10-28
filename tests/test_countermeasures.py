import numpy as np
import pandas as pd
import pytest

from nearmisslens import countermeasures as cm
from tests.test_conflicts import track


def test_turn_movement():
    straight = track(1, 0, 0, 10, 0)
    assert cm.turn_movement(straight) == "through"
    t = np.arange(40) / 10
    ang = np.where(t < 2, 0.0, (t - 2) * np.pi / 4)
    left = pd.DataFrame({"vx": 5 * np.cos(ang), "vy": 5 * np.sin(ang)})
    right = pd.DataFrame({"vx": 5 * np.cos(-ang), "vy": 5 * np.sin(-ang)})
    assert cm.turn_movement(left) == "left" and cm.turn_movement(right) == "right"


def test_crash_type_mapping():
    assert cm.crash_types_for(("vehicle", "pedestrian"), "crossing") == (["Vehicle/pedestrian"], "")
    types, note = cm.crash_types_for(("vehicle", "two_wheeler"), "crossing")
    assert "Angle" in types and note


def test_lpi_rule():
    c = cm.Candidate("Leading Pedestrian Interval", "9918", "LPI", "5★", 13.0, 0.87, "Vehicle/pedestrian", "All", "Signalized", "")
    assert not cm.site_check(c, "right", right_turn_signalised=False)[0]
    assert cm.site_check(c, "left", right_turn_signalised=False)[0]


@pytest.mark.skipif(not cm.CMF_PATH.exists(), reason="CMF Clearinghouse CSV not downloaded")
def test_candidates_from_real_database():
    db = cm.load_cmf()
    assert len(db) > 10000
    cands, rejected = cm.candidates(db, ("vehicle", "pedestrian"), "crossing")
    ids = {c.crfid for c in cands}
    assert cands and all(c.cmf < 1 for c in cands)
    assert any(r.get("crfid") == "9897" for r in rejected) or "9897" not in ids
