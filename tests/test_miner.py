import random

from nearmisslens import miner as M
from tests.test_agent import FakeClient, call, usage

LEFT = {"field": "pre_crash", "value": "making left turn"}
WITH = {"field": "ped_action", "value": "crossing with signal"}


def _ds(seed=0):
    """A corner where left turns into pedestrians crossing with the signal are common in both periods, one where a
    pattern is common only in the explore years, and 40 ordinary corners."""
    rng = random.Random(seed)
    crashes, corners = {}, []

    def add(cid, sealed, feats):
        crashes[cid] = {"date": "2025-01-01" if sealed else "2023-01-01", "f": feats}
        return cid

    def ordinary():
        f = {"pre_crash": [rng.choice(["going straight ahead", "making left turn", "making right turn", "backing"])],
             "ped_action": [rng.choice(["crossing with signal", "crossing against signal", "other actions"])]}
        f["outcome"] = [rng.choice(["pedestrian hurt", "only people in vehicles hurt"])]
        return f
    n = 0
    for c in range(40):
        ids = []
        for sealed in (False, True):
            for _ in range(60):
                n += 1
                ids.append(add(f"o{n}", sealed, ordinary()))
        corners.append({"slug": f"ord{c}", "ids": ids})
    ids = []
    for sealed in (False, True):
        for k in range(80):
            n += 1
            f = ordinary()
            if k < 40:
                f["pre_crash"], f["ped_action"] = ["making left turn"], ["crossing with signal"]
            ids.append(add(f"h{n}", sealed, f))
    corners.insert(0, {"slug": "hot", "ids": ids})
    ids = []
    for sealed in (False, True):
        for k in range(80):
            n += 1
            f = ordinary()
            if not sealed and k < 40:
                f["pre_crash"] = ["backing"]
            ids.append(add(f"f{n}", sealed, f))
    corners.insert(1, {"slug": "fluke", "ids": ids})
    return {"split": "2024-05-01", "corners": corners, "crashes": crashes}


def test_holm_and_sealed_confirmation():
    assert M.holm([0.001, 0.02, 0.04], 0.05) == [True, True, True]
    assert M.holm([0.001, 0.03, 0.04], 0.05) == [True, False, False]
    ds = _ds(); pool = M.Pool(ds)
    hot = M.score_arm(ds, pool, ds["corners"][0]["ids"], [[LEFT, WITH]], [[LEFT, WITH]])
    assert [c["pattern"] for c in hot["confirmed"]] == [M.key([LEFT, WITH])]
    back = [{"field": "pre_crash", "value": "backing"}]
    fluke = M.score_arm(ds, pool, ds["corners"][1]["ids"], [back], [back])
    assert fluke["explore_passed"] == 1 and fluke["confirmed"] == []  # strong early, gone in the sealed years


def test_every_attempt_counts_in_the_correction():
    ds = _ds(); pool = M.Pool(ds)
    ids = ds["corners"][0]["ids"]
    junk = [[{"field": "outcome", "value": "pedestrian hurt"}]] * 60
    one = M.score_arm(ds, pool, ids, [[LEFT]], [[LEFT]])
    many = M.score_arm(ds, pool, ids, [[LEFT]] + junk, [[LEFT]])
    assert many["tested"] == 61 and one["tested"] == 1
    assert len(many["confirmed"]) <= len(one["confirmed"])


def test_grid_greedy_and_null_corners():
    ds = _ds(); pool = M.Pool(ds)
    assert any(c["pattern"] == M.key([LEFT, WITH]) for c in M.greedy_arm(ds, pool, ds["corners"][0]["ids"])["confirmed"])
    assert M.grid_arm(ds, pool, ds["corners"][0]["ids"])["confirmed"]
    nulls = M.null_corners(ds, pool, ds["corners"][:5], seed=1)
    assert all(len(M.period(ds, n["ids"], False)) == 80 for n in nulls[:2])
    assert sum(len(M.greedy_arm(ds, pool, n["ids"])["confirmed"]) for n in nulls) <= 1


def test_agent_sees_only_explore_years_and_must_report_tested_patterns():
    ds = _ds(); pool = M.Pool(ds)
    pat = [LEFT, WITH]
    seen = {}
    fc = FakeClient([
        {"id": "r1", "output": [call("describe", {}, "c1")], "usage": usage()},
        {"id": "r2", "output": [call("finish", {"findings": [{"pattern": [LEFT], "mechanism": "left turns"}]}, "c2")],
         "usage": usage()},
        {"id": "r3", "output": [call("test_pattern", {"pattern": pat, "why": "LPI-type conflict"}, "c3")], "usage": usage()},
        {"id": "r4", "output": [call("finish", {"findings": [{"pattern": pat, "mechanism":
                                 "left-turning drivers hitting pedestrians crossing with the signal"}]}, "c4")],
         "usage": usage()},
    ])
    orig = fc.create_response

    def spy(payload):
        for item in payload["input"]:
            if item.get("type") == "function_call_output" and "crashes_in_earlier_years" in str(item.get("output")):
                seen["describe"] = item["output"]
        return orig(payload)
    fc.create_response = spy
    out = M.agent_arm(ds, pool, ds["corners"][0], fc, "corner-000001")
    assert '"crashes_in_earlier_years": 80' in seen["describe"]  # 80 explore crashes; the 80 sealed ones are hidden
    assert out["finished"] and out["tested"] == 1 and out["reported"] == 1
    assert out["confirmed"] and out["confirmed"][0]["mechanism"].startswith("left-turning")


def test_overclaiming_mechanisms_are_refused():
    ds = _ds(); pool = M.Pool(ds)
    pat = [LEFT, WITH]
    fc = FakeClient([
        {"id": "r1", "output": [call("test_pattern", {"pattern": pat, "why": "x"}, "c1")], "usage": usage()},
        {"id": "r2", "output": [call("finish", {"findings": [{"pattern": pat, "mechanism": "left turns caused these"}]}, "c2")],
         "usage": usage()},
        {"id": "r3", "output": [{"type": "message", "content": [{"type": "output_text", "text": "stop"}]}], "usage": usage()},
    ])
    out = M.agent_arm(ds, pool, ds["corners"][0], fc, "corner-000002")
    assert not out["finished"] and out["confirmed"] == []
