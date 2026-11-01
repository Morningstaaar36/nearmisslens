import numpy as np

from nearmisslens import sitecheck as S
from nearmisslens.segments import Detection

SHAPE = (768, 768, 3)


def det(x1, y1, x2, y2):
    return Detection(0, "o", "c", x1, y1, x2, y2, None, 0.9)


def test_gate_needs_both_models_to_agree():
    near = [det(380, 380, 400, 400)]  # at the centre
    assert S.decide({"answer": "present", "points": [[390, 390]]}, near, SHAPE)["gated"] == "present"
    assert S.decide({"answer": "present", "points": [[50, 50]]}, near, SHAPE)["gated"] == "unsure"  # SAM finds it elsewhere
    assert S.decide({"answer": "present", "points": [[390, 390]]}, [], SHAPE)["gated"] == "unsure"   # SAM finds nothing
    assert S.decide({"answer": "absent", "points": []}, [], SHAPE)["gated"] == "absent"
    assert S.decide({"answer": "absent", "points": []}, near, SHAPE)["gated"] == "unsure"           # SAM disagrees
    far = [det(0, 0, 30, 30)]  # outside the 40 m circle
    assert S.decide({"answer": "absent", "points": []}, far, SHAPE)["sam"] == "absent"


def test_score_counts_only_decided_corners_and_applies_the_rule():
    rows = []
    for k in range(10):
        ans = {a: {"spark": "present", "sam": "present", "gated": "present" if k < 8 else "unsure"} for a in S.ATTRS}
        rows.append({"answers": ans, "truth": {a: (k != 0) for a in S.ATTRS}})
    out = S.score(rows)
    g = out["bike_lane"]["gated"]
    assert g["decided"] == 8 and g["coverage"] == 0.8 and g["accuracy"] == 0.875
    assert out["bike_lane"]["used_in_product"] is True
    rows[1]["truth"] = {a: None for a in S.ATTRS}  # unknown truth is excluded
    assert S.score(rows)["median"]["gated"]["corners"] == 9


def test_wilson_interval():
    lo, hi = S.wilson(85, 100)
    assert 0.76 < lo < 0.78 and 0.90 < hi < 0.92
