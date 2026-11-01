"""The README's headline numbers are the committed results' numbers (validation/results/bench/*.json), so a rebuild that
changes a result fails here until the prose follows."""
import json

from nearmisslens.config import ROOT

BENCH = ROOT / "validation" / "results" / "bench"
README = (ROOT / "README.md").read_text()


def _load(name):
    return json.loads((BENCH / name).read_text())


def _has(text: str):
    assert text in README, f"README does not say {text!r}"


def test_city_plan_numbers():
    for city in ("nyc", "seattle", "dc", "sf"):
        s = _load(f"plan_{city}.json")["summary"]
        _has(f"${round(s['harm_usd_per_year'] / 1e6)} million")
    s = _load("plan_nyc.json")["summary"]
    _has(f"{round(s['textbook_crashes_avoided_per_year'])} crashes a year")
    _has(f"**{round(s['crashes_avoided_per_year_total'])}** ({round(s['crashes_avoided_per_year_after_rtm'])} after "
         "regression to the mean)")
    _has(f"at {s['corners_with_supported_fix']} corners")
    _has(f"not the only road owner at {s['corners_with_another_road_owner']} corners")
    _has(f"{s['repeat_risk_corners']['turn traffic calming']} corners already got turn calming")
    _has(f"At {len(_load('plan_nyc.json')['requests']['rerequests'])} corners, a leading pedestrian interval")
    for city in ("seattle", "dc", "sf"):
        s = _load(f"plan_{city}.json")["summary"]
        assert f"| {round(s['textbook_crashes_avoided_per_year'])} |" in README or \
            f"| {round(s['textbook_crashes_avoided_per_year'])}\n" in README, city


def test_red_team_and_applicability_numbers():
    ho = _load("experiment_T18_heldout.json")
    r, p = ho["registered_gate"], ho["patched_gate"]
    _has(f"{r['accepted']} of {r['false_claims']}")
    _has(f"{p['accepted']} of {p['false_claims']}")
    _has(f"{round(100 * ho['rule']['attack_success_cut'])}%")
    dev = _load("experiment_T18_dev.json")["score"]
    _has(f"{dev['accepted']} of {dev['false_claims']}")
    t19 = _load("experiment_T19.json")["score"]
    _has(f"{t19['gated']['all']['accuracy']:.2f} accuracy")


def test_causal_gate_numbers():
    t11 = _load("study_T11.json")
    g = t11["gates"]["lpi"]
    lpi = t11["runs"][g["primary"]][g["outcome"]]
    _has(f"{lpi['sites']:,} intersections")
    _has(f"−{round(100 * (1 - lpi['theta']))}%")
