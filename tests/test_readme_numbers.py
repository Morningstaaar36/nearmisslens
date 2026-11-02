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
    _has(f"**{round(s['crashes_avoided_per_year_total'])}** at {s['corners_with_supported_fix']} corners; "
         f"**{round(s['crashes_avoided_per_year_counted_once'])}** with each crash counted once, "
         f"**{round(s['crashes_avoided_per_year_counted_once_after_rtm'])}** after regression to the mean")
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


def test_claim_reading_numbers():
    t = _load("experiment_T20b.json")["scores"]
    for arm in ("regex", "model"):
        _has(f"{t[arm]['accepted']} of {t[arm]['false_claims']}")
        _has(f"{t[arm]['refused']} of {t[arm]['true_claims']}")


def test_desk_numbers():
    from nearmisslens.bench import desk_stats
    c, d = desk_stats(_load("experiment_T21c.json")), desk_stats(_load("experiment_T21d.json"))
    runs = [desk_stats(_load(f"experiment_{k}.json")) for k in ("T21c", "T21d", "T21e")]
    _has(f"On {sum(r['cases'] for r in runs)} fresh real cases")
    _has(f"published {sum(r['published'] for r in runs)}, and all {sum(r['verified'] for r in runs)} of their quotes")
    usd = sorted(r["usd_per_case"] for r in runs)
    _has(f"${usd[0]:.3f} to ${usd[-1]:.3f} a case")
    for r in runs[1:]:
        _has(f"| **{r['published']} of {r['cases']}** | **{r['verified']} of {r['quotes']}** |")
    from nearmisslens.baseline_desk import summary
    b = summary(_load("experiment_T24.json"))
    _has(f"{b['quotes_absent']} of the {b['quotes_verified'] + b['quotes_absent']} quotes")
    assert b["consistent"] == 0
    _has(f"None of the {b['number_findings']} sentences")
    _has(f"| {b['consistent']} / {b['differs']} / {b['not_checkable']} |")
    _has(f"| cases finished | {b['finished']} of {b['cases']} | {c['published']} of {c['cases']} |")
    _has(f"| Meta $ a case | ${b['usd_per_case']:.3f} | ${c['usd_per_case']:.3f} |")
    for run in ("T21", "T21b"):
        st = desk_stats(_load(f"experiment_{run}.json"))
        _has(f"| {st['published']} of {st['cases']} |")


def test_corner_watch_numbers():
    s = _load("experiment_T23.json")["summary"]
    _has(f"{s['frames']} frames from the traffic cameras at {s['with_daylight']} of the {s['cameras']} camera corners")
    _has(f"within ±1 person in {s['pack_within_1']} of {s['pack_checks']} sampled frames")
    assert s["pack_rule_met"] and not s["ranking_reported"]
    _has("packed counts: met; ranking: not reported (rule)")
    _has(f"Only {s['with_rate']} cameras saw the 20 people a rate needs")
    f = s["features"]
    _has(f"Of {sum(f.values())} layout answers, {f['present']} are present, {f['absent']} absent and {f['unsure']} unsure")
    _has(f"The run cost ${s['usd']:.2f} of Meta API")
