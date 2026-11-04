"""The headline numbers in README.md and EVIDENCE.md (the long version) are the committed results' numbers
(validation/results/bench/*.json), so a rebuild that
changes a result fails here until the prose follows."""
import json
import re

from nearmisslens.config import ROOT

BENCH = ROOT / "validation" / "results" / "bench"
README = (ROOT / "README.md").read_text() + "\n" + (ROOT / "EVIDENCE.md").read_text()


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


def test_t25_numbers():
    from nearmisslens.check_runs import summary
    s = summary(_load("experiment_T25.json"), "T25")
    assert s["rule_met"]
    _has(f"all {s['published_real']} real inputs published")
    _has(f"all {s['quotes_verified']} of their quotes")
    _has(f"{s['published_real']} of {s['real']} real inputs")
    _has(f"{s['quotes_verified']} of {s['quotes_published']} quotes verified")
    _has(f"${s['mean_usd']:.3f} an input")


def test_t26_numbers():
    from nearmisslens.review import run_summary
    sp = json.loads((ROOT / "validation" / "experiments" / "T26.json").read_text())
    s = run_summary(_load("experiment_T26.json"), sp)
    assert s["rule_met"]
    _has(f"{s['published']} of {s['inputs']} memos published")
    _has(f"${s['mean_usd']:.3f} a review")
    _has(f"{s['inputs']} real proposed projects")


def test_t27_numbers():
    from nearmisslens.review import run_summary
    sp = json.loads((ROOT / "validation" / "experiments" / "T27.json").read_text())
    s = run_summary(_load("experiment_T27.json"), sp)
    assert s["rule_met"] and s["on_proposed_corner"] == s["published"]
    _has(f"{s['published']} of {s['inputs']} memos, all on the proposed corner, at ${s['mean_usd']:.3f} a review")


def test_t28_numbers():
    from nearmisslens.review import run_summary
    sp = json.loads((ROOT / "validation" / "experiments" / "T28.json").read_text())
    s = run_summary(_load("experiment_T28.json"), sp)
    t27 = run_summary(_load("experiment_T27.json"), json.loads((ROOT / "validation" / "experiments" / "T27.json").read_text()))
    assert s["rule_met"] and s["objections_on_the_verdict"] == 0
    _has(f"{s['objections_kept']} in all, against {t27['objections_kept']}")
    _has(f"${s['mean_usd']:.3f} a review")
    _has(f"{s['memos_with_3_objections']} of {s['published']} memos, {s['objections_kept']} objections")


def test_t30_numbers():
    from nearmisslens.intake import run_summary
    sp = json.loads((ROOT / "validation" / "experiments" / "T30c.json").read_text())
    s = run_summary(_load("experiment_T30c.json"), sp)
    assert s["rule_met"] and s["controls_empty"]
    _has(f"all {s['hand_found']} of the {s['hand_projects']} projects we had collected by hand")
    _has(f"({sum(r['kept'] for r in s['rows'])} projects kept")
    _has(f"${s['mean_usd_per_readable_page']:.3f} a page")
    for run in ("T30", "T30b"):
        assert not run_summary(_load(f"experiment_{run}.json"), sp)["rule_met"]


def test_t31_numbers():
    a, b = _load("experiment_T31.json")["summary"], _load("experiment_T31b.json")["summary"]
    assert not a["rule_met"] and not b["rule_met"]
    _has(f"not met / not met ({a['tool_agree']} and {b['tool_agree']} of 10; mean error {a['tool_mean_abs_error']} and "
         f"{b['tool_mean_abs_error']} crashes, against the 100 m circle's {a['circle_mean_abs_error']} and "
         f"{b['circle_mean_abs_error']})")
    _has(f"within {b['tool_mean_abs_error']} injury crashes on average where the 100 m circle was off by "
         f"{b['circle_mean_abs_error']}, but it agreed within 15% at only {b['tool_agree']} of 10")


def test_t32_numbers():
    c = _load("experiment_T32.json")["summary"]
    frozen = {(r["city"], r["corner"]): r["tool_injury_crashes"] for r in _load("experiment_T32_tool_before_counts.json")["tool"]}
    scored = {(r["city"], r["corner"]): r["tool"] for r in _load("experiment_T32.json")["comparison"]}
    assert frozen == scored  # the counts scored are the ones saved before the independent counts existed
    assert not c["rule_met"]
    _has(f"agrees at {c['tool_agree']} of 10 fresh corners")
    _has(f"mean error {c['tool_mean_abs_error']} crashes against the 100 m circle's {c['circle_mean_abs_error']}")
    _has(f"not met ({c['tool_agree']} of 10; mean error {c['tool_mean_abs_error']} crashes")


def test_t29b_numbers():
    from nearmisslens.portfolio import run_summary
    sp = json.loads((ROOT / "validation" / "experiments" / "T29b.json").read_text())
    s = run_summary(_load("experiment_T29b.json"), sp)
    assert s["rule_met"] and s["ranking_reproduced"] and s["on_proposed_corner"] == s["reviewed"]
    _has(f"{s['reviewed']} of the {s['proposals']} proposals were reviewed, every one on its own corner, at "
         f"${s['mean_usd']:.3f} a proposal")
    _has(f"met ({s['reviewed']} of {s['proposals']} reviewed, all on their corner, ranking rebuilt exactly)")
