"""The README's headline numbers are the committed results' numbers (validation/results/bench/*.json), so a rebuild that
changes a result fails here until the prose follows."""
import json
import re

from nearmisslens.config import ROOT

BENCH = ROOT / "validation" / "results" / "bench"
README = (ROOT / "README.md").read_text()


def _load(name):
    return json.loads((BENCH / name).read_text())


def _says(text: str) -> bool:
    """The phrase as written, not inside a longer word or number: '21 of 21' does not match '121 of 21' or '21 of 210',
    and '$0.12' does not match '$0.126'."""
    lead = r"(?<!\w)(?<!\d\.)" if text[:1].isalnum() else ""
    tail = r"(?!\w)(?!\.\d)" if text[-1:].isalnum() else ""
    return re.search(lead + re.escape(text) + tail, README) is not None


def _has(text: str):
    assert _says(text), f"README does not say {text!r}"


def test_a_number_must_match_exactly():
    global README
    saved, README = README, "published 121 of 21 at $0.126 a case; 68 of 68."
    try:
        assert not _says("21 of 21") and not _says("$0.12") and not _says("68 of 6")
        assert _says("121 of 21") and _says("$0.126") and _says("68 of 68")
    finally:
        README = saved


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
        assert _says(f"| {round(s['textbook_crashes_avoided_per_year'])} |") or \
            _says(f"| {round(s['textbook_crashes_avoided_per_year'])}\n"), city


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
    _has(f"Of the {b['number_findings']} sentences it wrote with numbers about the case, {b['consistent'] + b['differs']} "
         f"states a count the city's crash record can test, and it differs from the record; the other "
         f"{b['not_checkable']} cannot be checked")
    assert b["differs"] == 1
    _has(f"| {b['consistent']} / {b['differs']} / {b['not_checkable']} |")
    _has(f"| cases finished | {b['finished']} of {b['cases']} | {c['published']} of {c['cases']} |")
    _has(f"| Meta $ a case | ${b['usd_per_case']:.3f} | ${c['usd_per_case']:.3f} |")
    for run in ("T21", "T21b"):
        st = desk_stats(_load(f"experiment_{run}.json"))
        _has(f"| {st['published']} of {st['cases']} |")


def test_corner_watch_numbers():
    s = _load("experiment_T23.json")["summary"]
    _has(f"{s['frames']} frames from the traffic cameras at {s['with_daylight']} of the {s['cameras']} camera corners")
    assert s["pack_rule_met"] and not s["ranking_reported"]
    _has("packed counts: met; ranking: not reported (rule)")
    _has(f"only {s['with_rate']} cameras saw the 20 people a rate needs")
    b = _load("experiment_T23b.json")["summary"]
    rows = [r for r in _load("experiment_T23b.json")["rows"] if r.get("pack_check")]
    diffs = [c["video"] - c["image"] for r in rows for c in r["pack_check"]]
    assert b["pack_rule_met"] and not b["ranking_reported"] and all(d <= 0 for d in diffs)  # "every disagreement ... fewer"
    _has(f"used {b['frames']} frames")
    _has(f"within ±1 person in {b['pack_within_1']} of {b['pack_checks']} sampled frames (rule met)")
    _has(f"{b['with_rate']} cameras saw at least 20 people")
    _has(f"{b['with_rate']} of 20 cameras")
    f = b["features"]
    _has(f"Of {sum(f.values())} layout answers in T23b, {f['present']} are present, {f['absent']} absent and {f['unsure']} unsure")
    _has(f"cost ${s['usd']:.2f} and ${b['usd']:.2f} of Meta API")


def test_calibrated_rank_and_unknown_control_counts():
    t14b = _load("experiment_T14b.json")["programs"]
    ny = {r["part"]: r["null_rank"] for r in t14b if r["study"] == "T11"}
    _has(f"beats {round(100 * (1 - ny['all sites']))}% of fakes on all sites and "
         f"{100 * (1 - ny['held-out half']):g}% on the held-out half")
    import glob
    from nearmisslens.config import ROOT
    reps = [json.loads(open(f).read()) for f in glob.glob(str(ROOT / "docs" / "data" / "nyc" / "j" / "*.json"))]
    unknown = sum(((r.get("findings") or {}).get("choose_fixes") or {}).get("control") == "unknown" for r in reps)
    _has(f"At {unknown} of the {len(reps)} New York corners on the site")


def test_red_team_drops_and_hardened_refusals():
    r = _load("experiment_T20b.json")
    _has(f"{r['dropped_unverified']} whose spec did not check out against the receipt were dropped")
    _has(f"refuses {round(100 * r['scores_hardened_posthoc']['model']['false_refusal'])}% of true ones")
