import json

import pandas as pd

from nearmisslens import panel
from tests.test_agent import FakeClient, call, usage

MEMO = "Hotspots are 15 m cells ranked per 1,000 road users (95% CI)."


def facts():
    kept = {"psc": "Backplates with Retroreflective Borders", "crfid": "1447", "name": "install signal backplates",
            "stars": "not rated", "crf_pct": 50.0, "cmf": 0.5, "crash_type": "Angle", "severity": "All",
            "control": "Signalized", "note": ""}
    finding = {"rank": 1, "x": -22.5, "y": -22.5, "cell_m": 15.0, "events": 12, "users": 73, "rate_per_1000": 164.4,
               "ci95": [84.9, 287.1], "by_measure": {"TTC": 12}, "examples": [],
               "dominant": {"pair": ["vehicle", "vehicle"], "type": "crossing", "events": 6},
               "countermeasures": [kept],
               "rejected": [{"psc": "Roundabouts", "crfid": "4096", "reason": "CMF 1.100 >= 1 (no reduction) for Angle"}]}
    return {"observed_s": 408.0, "users": {"vehicle": 347}, "control": "Signalized", "right_turn_signalised": False,
            "conflicts": {"total": 12, "by_measure": {"TTC": 12}, "by_type": {"crossing": 12}},
            "thresholds": {"pet_s": 1.5, "ttc_s": 1.5, "cell_m": 15.0, "min_hotspot_events": 2}, "findings": [finding]}


def cmf_db():
    return pd.DataFrame([{"crfid": "1447", "name": "install signal backplates", "cmf": 0.5, "crf_pct": 50.0,
                          "stars": float("nan"), "crash_type": "Angle", "severity": "All", "control": "Signalized",
                          "area": "Urban", "country": "USA", "citation": "Sayed et al. 2007"}])


def test_grounding_accepts_data_and_rejects_inventions():
    g = panel.Grounding(facts(), MEMO)
    assert g.text("Hotspot 1: 12 conflicts, 164 per 1,000 (CI 84.9-287.1); CMF 1447 cuts angle crashes 50%.") == []
    errors = g.text("Hotspot 2 has 61.7 conflicts per hour; CMF 9999 helps.")
    assert any("hotspot 2" in e for e in errors)
    assert any("CMF 9999" in e for e in errors)
    assert any("number 61.7" in e for e in errors)


def test_proposals_must_use_kept_countermeasures_and_cover_hotspots():
    g = panel.Grounding(facts(), MEMO)
    assert panel.check_proposals(g, [{"rank": 1, "crfid": "1447", "reason": "12 crossing conflicts"}]) == []
    errors = panel.check_proposals(g, [{"rank": 1, "crfid": "4096", "reason": "roundabouts"}])
    assert any("not among hotspot 1's countermeasures" in e for e in errors)
    assert panel.check_proposals(g, []) == ["hotspot 1 has countermeasures but no recommendation"]


def test_decisions_cover_every_proposal_once():
    g = panel.Grounding(facts(), MEMO)
    proposals = [{"rank": 1, "crfid": "1447", "psc": "Backplates", "reason": ""}]
    assert panel.check_decisions(g, proposals, [], "memo") == ["no decision on CMF 1447 for hotspot 1"]
    twice = [{"rank": 1, "crfid": "1447", "accept": True, "reason": "ok"}] * 2
    assert any("more than once" in e for e in panel.check_decisions(g, proposals, twice, "memo"))


def reply(rid, name, args):
    return {"id": rid, "output": [call(name, args, rid)], "usage": usage()}


def test_panel_runs_three_agents_and_records_caught_claims(tmp_path):
    good = {"recommendations": [{"rank": 1, "crfid": "1447", "reason": "12 crossing conflicts; CMF 1447 is 0.5"}]}
    decisions = [{"rank": 1, "crfid": "1447", "accept": True, "reason": "addresses crossing conflicts"}]
    fc = FakeClient([
        reply("p1", "site_summary", {}),
        reply("p2", "finish", {"recommendations": [{"rank": 1, "crfid": "4096", "reason": "roundabouts"}]}),
        reply("p3", "finish", good),
        reply("s1", "cmf", {"crfid": "1447"}),
        reply("s2", "finish", {"objections": [{"rank": 1, "crfid": "1447", "blocking": False,
                                               "objection": "CMF 1447 is unrated, from a 2007 study"}]}),
        reply("j1", "finish", {"decisions": decisions, "memo": "Backplates cut crashes by 61.7%."}),
        reply("j2", "finish", {"decisions": decisions, "memo": "Hotspot 1: consider backplates (CMF 1447)."}),
    ])
    result = panel.run_panel(fc, facts(), MEMO, cmf_db(), "test")
    assert result["status"] == "complete" and not fc.responses
    assert [len(s["rejected_attempts"]) for s in result["stages"]] == [1, 0, 1]
    assert result["caught"] == 2
    assert result["proposals"][0]["psc"] == "Backplates with Retroreflective Borders"
    assert fc.payloads[3]["model"] == panel.SKEPTIC_MODEL and fc.payloads[5]["model"] == panel.ARBITER_MODEL
    panel.write(result, tmp_path, "test")
    md = (tmp_path / "panel.md").read_text()
    assert "rejected: memo: number 61.7 does not appear" in md and "| 1 | Backplates with Retroreflective Borders | 1447 | accept |" in md
    assert json.loads((tmp_path / "panel.json").read_text())["status"] == "complete"


def test_panel_stops_when_an_agent_never_satisfies_the_checker():
    bad = {"recommendations": [{"rank": 1, "crfid": "4096", "reason": "roundabouts"}]}
    fc = FakeClient([reply(f"p{k}", "finish", bad) for k in range(panel.MAX_TURNS)])
    result = panel.run_panel(fc, facts(), MEMO, cmf_db(), "test")
    assert result["status"] == "proposer did not finish"
    assert result["stages"][0]["stopped"] == "max_turns"
