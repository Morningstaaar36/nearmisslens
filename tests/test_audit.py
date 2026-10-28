import numpy as np
import pandas as pd

from nearmisslens import audit
from tests.test_movements import path


def states_for(uid, points, t0, cls="vehicle"):
    p = path(uid, points, cls=cls)
    p["t"] += t0
    p["frame"] = np.round(p["t"] * 10).astype(int) + 1
    p["yaw"] = np.arctan2(p["vy"], p["vx"])
    p["length"], p["width"] = (4.5, 1.8) if cls == "vehicle" else (0.6, 0.6)
    return p


def junction(n_pairs=3):
    parts = []
    for k in range(n_pairs):
        t0 = 20.0 * k
        parts.append(states_for(f"a{k}", [(-40, -2), (40, -2)], t0))
        parts.append(states_for(f"b{k}", [(2, -40), (2, 2), (-40, 2)], t0 + 0.6))
    return pd.concat(parts, ignore_index=True)


def fake_cmf():
    rows = [("1", "Install left-turn lane", "Angle", "Signalized", 0.70, 4, 30.0),
            ("2", "Install backplates with retroreflective borders", "Angle", "Signalized", 0.50, 4, 50.0),
            ("3", "Install left-turn lane", "Angle", "Signalized", 1.20, 4, -20.0)]
    return pd.DataFrame([{"crfid": i, "name": n.lower(), "crash_type": c, "control": ctl, "cmf": v, "stars": s,
                          "crf_pct": r, "severity": "All", "category": "", "subcategory": "", "area": "", "country": "",
                          "citation": ""} for i, n, c, ctl, v, s, r in rows])


def test_audit_finds_hotspot_and_checks_countermeasures_against_evidence():
    st = junction()
    signals = pd.DataFrame({"direction": ["W", "S"], "turn": ["s", "l"], "begin_time": [0, 0],
                            "end_time": [1000, 1000], "state": ["G", "G"]})
    facts = audit.audit(st, fake_cmf(), signals=signals, control="Signalized", right_turn_signalised=False)
    assert facts["conflicts"]["total"] == 3 and facts["findings"]
    f = facts["findings"][0]
    assert f["events"] == 3 and f["dominant"]["pair"] == ["vehicle", "vehicle"]
    assert f["dominant"]["movements"].get("left") == 3 and f["dominant"]["entry_signal"] == {"G": 6}
    kept = {c["psc"] for c in f["countermeasures"]}
    assert kept == {"Dedicated Left- and Right-Turn Lanes at Intersections"}
    reasons = {r["psc"]: r["reason"] for r in f["rejected"]}
    assert "yellow or red" in reasons["Backplates with Retroreflective Borders"]
    md = audit.memo(facts, "synthetic", "test")
    assert "Hotspot 1" in md and "CMF ≥ 1; IDs 3" in md


def test_red_entry_enables_signal_countermeasures():
    st = junction()
    signals = pd.DataFrame({"direction": ["W", "S"], "turn": ["s", "l"], "begin_time": [0, 0],
                            "end_time": [1000, 1000], "state": ["r", "G"]})
    facts = audit.audit(st, fake_cmf(), signals=signals, control="Signalized", right_turn_signalised=False)
    kept = {c["psc"] for c in facts["findings"][0]["countermeasures"]}
    assert "Backplates with Retroreflective Borders" in kept


def test_audit_without_conflicts():
    st = states_for("a", [(-40, -2), (40, -2)], 0.0)
    facts = audit.audit(st, fake_cmf(), signals=None, control=None, right_turn_signalised=False)
    assert facts["conflicts"]["total"] == 0 and facts["findings"] == []
    assert "No cell reached" in audit.memo(facts, "x", "y")
