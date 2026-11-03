"""Before you commit: code sets the verdict, the red team's objections are kept only when their fact checks out, and
the memo gate holds the model to both (no model, no network)."""
import pytest

from nearmisslens import review

FX = {"crashes": {"injury_crashes": 40, "crashes": 90},
      "options": [
          {"countermeasure": "Leading Pedestrian Interval", "evidence": "FHWA-cited", "targets": "pedestrian",
           "target_crashes_per_year": 2.0, "expected_crashes_avoided_per_year": 0.6,
           "injury_crashes_avoided_per_year": 0.6, "break_even_cost_usd": 1900000.0, "cmf": 0.7},
          {"countermeasure": "Backplates with Retroreflective Borders", "evidence": "FHWA-cited", "targets": "all",
           "target_crashes_per_year": 8.0, "expected_crashes_avoided_per_year": 1.2,
           "injury_crashes_avoided_per_year": 1.6, "break_even_cost_usd": 5000000.0, "cmf": 0.85},
          {"countermeasure": "Lighting", "evidence": "needs a site check", "targets": "night",
           "target_crashes_per_year": 1.0, "injury_crashes_avoided_per_year": 0.2, "break_even_cost_usd": 600000.0,
           "verify_on_site": "street lighting is poor at night"},
          {"countermeasure": "Rectangular Rapid Flashing Beacons", "evidence": "contradicted here",
           "targets": "pedestrian", "target_crashes_per_year": 2.0, "injury_crashes_avoided_per_year": 0.5,
           "break_even_cost_usd": 1500000.0}],
      "not_estimated": [{"countermeasure": "Roundabouts", "reason": "no CMF record fits a signalized site"}],
      "in_place": [{"countermeasure": "Yellow Change Intervals", "year": 2022}], "control": "signal"}


@pytest.mark.parametrize("cm,cost,verdict", [
    ("Backplates with Retroreflective Borders", 20000, "proceed"),
    ("Leading Pedestrian Interval", 15000, "compare_alternative"),  # backplates: 1.6 a year, over twice its 0.6
    ("Leading Pedestrian Interval", 5000000, "reconsider"),  # costs more than its life benefit
    ("Lighting", None, "proceed_after_site_check"),
    ("Rectangular Rapid Flashing Beacons", None, "reconsider"),  # the city's own record contradicts it
    ("Roundabouts", None, "outside_evidence"),  # no study fits the site: not evidence against it
    ("Yellow Change Intervals", None, "reconsider"),  # already installed
])
def test_code_sets_the_verdict(cm, cost, verdict):
    a = review.appraise(FX, cm, cost)
    assert a["verdict"] == verdict, a["reasons"]
    assert a["verdict_text"] == review.VERDICTS[verdict] and a["reasons"]


def test_the_alternative_is_named_with_what_each_targets():
    a = review.appraise(FX, "Leading Pedestrian Interval", 15000)
    assert a["best_alternative"]["countermeasure"] == "Backplates with Retroreflective Borders"
    assert "targets all crashes" in a["reasons"][0] and a["benefit_cost_ratio"] == round(1900000 / 15000, 1)


def test_no_target_crashes_means_reconsider():
    fx = {**FX, "options": [{**FX["options"][0], "target_crashes_per_year": 0}]}
    assert review.appraise(fx, "Leading Pedestrian Interval", None)["verdict"] == "reconsider"


@pytest.mark.parametrize("found,value,ok", [
    (0.6, "0.6", True), (1900000.0, "$1,900,000", True), (100, "1", False), ("FHWA-cited", "fhwa-cited", True),
    ("needs a site check", "site", True), ("needs a site check", "si", False), ("signal", "stop", False),
    (None, "x", False), (40, "forty", False)])
def test_an_objection_fact_must_be_the_receipts_value(found, value, ok):
    assert review._matches(found, value) is ok


class FakeOpen:
    """Stands in for Muse Spark Open: the red team's objections arrive through its submit tool."""


def _review_with_receipts():
    rv = review.Review("zz")
    rv.proposal = {"address": "A St & B Ave, Zedburg", "countermeasure": "Leading Pedestrian Interval",
                   "cost_usd": 15000.0, "goal": "fewer pedestrians hit"}
    rv.desk.receipt("proposal", rv.proposal)
    rv.desk.receipt("choose_fixes", FX)
    rv.appraisal = review.appraise_proposal(FX, [{"countermeasure": "Leading Pedestrian Interval", "what": "LPI"}],
                                            15000.0, "this fix only")
    rv.desk.receipt("appraisal", rv.appraisal)
    return rv


def test_the_red_team_keeps_only_objections_whose_fact_checks_out(monkeypatch):
    rv = _review_with_receipts()

    def fake_run_agent(client, model, inst, task, tools, *a, **k):
        res = tools[0].fn(objections=[
            {"objection": "Backplates would do more", "receipt": "D3", "field": "best_alternative.injury_crashes_avoided_per_year", "value": "1.6"},
            {"objection": "The evidence is weak", "receipt": "D2", "field": "options.0.evidence", "value": "national studies"},
            {"objection": "No such receipt", "receipt": "D9", "field": "x", "value": "1"}])
        # fewer than three kept: the red team is asked once for replacements, and the kept one stays
        assert "error" in res and "replacements" in res["error"] and len(res["dropped"]) == 2
        again = tools[0].fn(objections=[
            {"objection": "The verdict says proceed", "receipt": "D3", "field": "verdict", "value": "proceed"},
            {"objection": "Same fact again", "receipt": "D3", "field": "best_alternative.injury_crashes_avoided_per_year", "value": "1.6"}])
        assert again["ok"] and again["kept"] == 1 and again["dropped"] == 4
        assert "error" in tools[0].fn(objections=[])  # a third submit is refused

        class R:
            usd, stopped = 0.004, "finished"
        return R()
    monkeypatch.setattr(review, "run_agent", fake_run_agent)
    out = review.red_team(rv, FakeOpen())
    assert [o["id"] for o in out["kept"]] == ["O1"] and out["kept"][0]["value"] == 1.6
    assert "holds 'FHWA-cited'" in out["dropped"][0]["why"] and rv.red_team_usd == 0.004
    assert "restates the decision" in out["dropped"][2]["why"] and "already rests" in out["dropped"][3]["why"]
    assert rv.dropped == out["dropped"]


def test_the_red_team_is_shown_every_fact_but_the_verdict_itself():
    rv = _review_with_receipts()
    fs = review.facts(review._compact(rv.desk))
    assert any(f["field"] == "best_alternative.injury_crashes_avoided_per_year" for f in fs)
    assert not any(review.RESTATES.search(f["field"]) for f in fs)


def test_the_memo_gate_holds_the_verdict_the_numbers_and_the_answers(monkeypatch):
    rv = _review_with_receipts()
    rv.objections = [{"id": "O1", "objection": "Backplates would do more", "receipt": "D3",
                      "field": "best_alternative.injury_crashes_avoided_per_year", "value": 1.6}]
    ts = {t.name: t for t in review.tools(rv, None, None, None)}
    good = [{"text": "Backplates with Retroreflective Borders are expected to avoid 1.6 injury crashes a year here.", "receipt": "D3"},
            {"text": "A leading pedestrian interval is expected to avoid 0.6 injury crashes a year here.", "receipt": "D3"},
            {"text": "The stated cost is $15,000.", "receipt": "D1"}]
    ans = [{"objection": "O1", "answer": "Both can be done; backplates target all crashes.", "receipt": "D3"}]
    v = "compare_alternative"
    parts = [{"countermeasure": "Leading Pedestrian Interval", "verdict": v}]
    assert ts["check_memo"].fn(summary="Compare before committing.", verdict=v, findings=good, answers=ans,
                               parts=parts)["would_publish"]
    bad_verdict = ts["finish"].fn(summary="Go ahead.", verdict="proceed", findings=good, answers=ans, parts=parts)
    assert "the verdict is the appraisal's" in " ".join(bad_verdict["errors"])
    no_parts = ts["finish"].fn(summary="Compare.", verdict=v, findings=good, answers=ans, parts=[])
    assert any("list every part" in e for e in no_parts["errors"])
    unanswered = ts["finish"].fn(summary="Compare.", verdict=v, findings=good, answers=[], parts=parts)
    assert any("O1" in e for e in unanswered["errors"])
    wrong_number = ts["finish"].fn(summary="Compare.", verdict=v, answers=ans, parts=parts,
                                   findings=good[:2] + [{"text": "It is expected to avoid 4.2 injury crashes a year.", "receipt": "D3"}])
    assert "error" in wrong_number and rv.final is None
    assert ts["finish"].fn(summary="Compare before committing.", verdict=v, findings=good, answers=ans,
                           parts=parts) == {"ok": True}
    assert rv.final["verdict"] == v


def test_the_proposal_must_name_a_federal_countermeasure():
    rv = review.Review("zz")
    ts = {t.name: t for t in review.tools(rv, None, None, None)}
    reg = lambda parts, cost=0, covers="not stated": ts["register_proposal"].fn(
        address="A & B", parts=parts, cost_usd=cost, cost_covers=covers, goal="x")
    assert "error" in reg([{"countermeasure": "Magic paint", "what": "x"}])
    assert "error" in reg([])
    ok = reg([{"countermeasure": "Lighting", "what": "lights"}])
    assert ok["receipt"] == "D1" and rv.proposal["cost_usd"] is None
    assert "error" in ts["appraise"].fn()  # nothing investigated yet


def test_an_unsupported_city_gets_a_plain_answer():
    assert review.review("LPI at A & B", "atlantis")["status"] == "unsupported_city"


def test_the_test_set_is_real_split_and_place_free_in_code():
    import json
    rows = json.loads(review.EXAMPLES.read_text())["proposals"]
    assert {r["split"] for r in rows} == {"registered", "independent", "team", "held_out", "independent2"}
    assert all(r["source"].startswith("https://") and r["city"] and r["proposal"] for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)
    spec = json.loads((review.EXAMPLES.parent.parent / "experiments" / "T26.json").read_text())
    reg = review.registered_inputs(spec)
    assert len(reg) == 7 and all(r["split"] == "registered" for r in reg)


def test_a_registered_run_is_scored_by_its_rule():
    spec = {"rule": {"min_published": 2, "max_mean_usd": 0.15}}
    c = lambda st, v, o: {"status": st, "verdict": v, "memo": {"verdict": v} if st == "published" else None,
                          "objections": o, "cost_usd": {"meta": 0.03, "open_weights_red_team": 0.01}, "seconds": 100}
    s = review.run_summary({"cases": [c("published", "proceed", [{}]), c("published", "reconsider", []),
                                      c("abstained", None, None)]}, spec)
    assert s["rule_met"] and s["published"] == 2 and s["verdicts"]["reconsider"] == 1 and s["mean_usd"] == 0.04


def test_the_site_gets_the_saved_reviews_and_the_proposals_to_try(monkeypatch, tmp_path):
    import json
    from nearmisslens import evaluate, pages
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "experiment_T26.json").write_text(json.dumps({"id": "T26", "cases": [
        {"id": "x", "status": "published", "verdict": "proceed", "memo": {"verdict": "proceed", "summary": "Plate ABC1234."},
         "objections": [], "cost_usd": {"meta": 0.03, "open_weights_red_team": 0.01}, "seconds": 90}]}))
    monkeypatch.setattr(evaluate, "RESULTS_DIR", tmp_path)
    out = tmp_path / "site"
    out.mkdir()
    pages.reviews_page(out)
    blob = json.loads((out / "reviews.json").read_text())
    assert blob["summary"]["published"] == 1 and blob["cases"][0]["verdict"] == "proceed"
    assert blob["try"] and all(t["split"] in ("independent", "team", "held_out", "independent2") for t in blob["try"])
    assert "ABC1234" not in (out / "reviews.json").read_text()


def test_the_check_test_set_says_what_each_input_should_get():
    import json
    from nearmisslens import check
    d = json.loads((review.EXAMPLES.parent / "checks_testset.json").read_text())
    assert {i["split"] for i in d["inputs"]} == {"independent", "team", "held_out", "independent2"}
    assert all(i["expect"] and i["kind"] in check.KINDS for i in d["inputs"])
    assert len({i["id"] for i in d["inputs"]}) == len(d["inputs"])


@pytest.mark.parametrize("proposed,corner,same", [
    ("East 169th Street & Rev James A Polite Avenue, Bronx", "East 169th Street & Prospect Avenue, Bronx", False),
    ("East 169th Street & Rev James A Polite Avenue, Bronx", "East 169th Street & Reverend James A. Polite Avenue, Bronx", True),
    ("22nd Street NW & L Street NW", "22nd Street Northwest & L Street Northwest, Washington DC", True),
    ("15th Ave S & S Lander St", "15th Avenue South & South Lander Street, Seattle", True),
    ("Ridge Avenue & Hollywood Avenue", "West Hollywood Avenue & North Ridge Avenue, Chicago", True),
    ("Ridge Avenue & Hollywood Avenue", "North Ridge Avenue & West Thorndale Avenue, Chicago", False),
])
def test_a_review_is_only_of_the_intersection_proposed(proposed, corner, same):
    """T26: a proposal's street was not found, and the agent reviewed a nearby corner instead. The appraisal now
    refuses a case about any intersection but the one proposed."""
    assert review.same_corner(proposed, corner) is same


def test_the_appraisal_refuses_another_corner():
    rv = review.Review("zz")
    ts = {t.name: t for t in review.tools(rv, None, None, None)}
    ts["register_proposal"].fn(address="East 169th Street & Rev James A Polite Avenue, Bronx",
                               parts=[{"countermeasure": "Lighting", "what": "lights"}], cost_usd=0,
                               cost_covers="not stated", goal="x")
    rv.desk.receipt("choose_fixes", FX)
    rv.desk.report = {"junction": {"name": "East 169th Street & Prospect Avenue, Bronx"}}
    out = ts["appraise"].fn()
    assert "not the proposed intersection" in out["error"] and rv.appraisal is None
    assert rv.off_corner == "East 169th Street & Prospect Avenue, Bronx"


def test_an_initial_matches_with_or_without_its_period():
    import re
    from nearmisslens import brief
    pat = brief._directional("Reverend James A Polite Avenue")
    assert re.fullmatch(pat, "Reverend James A. Polite Avenue", re.I) and re.fullmatch(pat, "Reverend James A Polite Avenue", re.I)
    assert brief.address_variants("Rev James A Polite Ave & E 169th St, Bronx")[1].startswith("Reverend James A Polite Avenue")


def test_no_target_crashes_is_reconsider_but_no_fitting_study_is_outside_the_evidence():
    """T26 review: 'reconsider' had lumped 'the record shows none of the crashes it targets' with 'no study fits this
    site' (a crosswalk where the only record was measured at school crossings). The second is not evidence against."""
    fx = {**FX, "not_estimated": [
        {"countermeasure": "Medians and Pedestrian Refuge Islands in Urban and Suburban Areas",
         "reason": "the record has no pedestrian injury crashes"},
        {"countermeasure": "Crosswalk Visibility Enhancements",
         "reason": "CMF 2697 was measured only at school crossings, and this site is not known to be one"},
        {"countermeasure": "Pedestrian Hybrid Beacons",
         "reason": "the record has no pedestrian injury crashes; its records are for uncontrolled sites"}]}
    assert review.appraise(fx, "Medians and Pedestrian Refuge Islands in Urban and Suburban Areas", None)["verdict"] == "reconsider"
    assert review.appraise(fx, "Crosswalk Visibility Enhancements", None)["verdict"] == "outside_evidence"
    assert review.appraise(fx, "Pedestrian Hybrid Beacons", None)["verdict"] == "outside_evidence"



def test_every_part_is_appraised_and_a_mixed_proposal_is_decided_part_by_part():
    """Independent test: 'an LPI and a protected left-turn phase' was cut down to the LPI."""
    parts = [{"countermeasure": "Yellow Change Intervals", "what": "LPI already there"},
             {"countermeasure": "other", "what": "a protected left-turn phase"}]
    a = review.appraise_proposal(FX, parts, None, "not stated")
    assert [p["verdict"] for p in a["parts"]] == ["reconsider", "outside_evidence"] and a["verdict"] == "mixed"
    assert "protected left-turn phase" in a["parts"][1]["reasons"][0]


def test_a_package_cost_is_not_charged_to_one_fix():
    """Independent test: a $1.3M package (realignment, signals, crosswalks) was charged to one beacon."""
    one = [{"countermeasure": "Leading Pedestrian Interval", "what": "LPI"}]
    assert review.appraise_proposal(FX, one, 5000000, "this fix only")["verdict"] == "reconsider"
    pkg = review.appraise_proposal(FX, one, 5000000, "a package with other work")
    assert pkg["verdict"] != "reconsider" and any("not compared with one fix" in r for r in pkg["reasons"])


def test_a_control_the_map_contradicts_is_confirmed_on_site_and_estimated_as_proposed():
    """Independent test: an unsignalized five-way corner, mapped as signalized from a signal within 80 m, had its
    beacon refused and signal-only fixes recommended. The beacon is now estimated as at an uncontrolled site."""
    seen = []
    uncontrolled = {**FX, "control": "Uncontrolled",
                    "options": [{"countermeasure": "Pedestrian Hybrid Beacons", "evidence": "FHWA-cited",
                                 "targets": "pedestrian", "target_crashes_per_year": 1.2,
                                 "injury_crashes_avoided_per_year": 0.5, "break_even_cost_usd": 1500000}]}
    a = review.appraise_proposal(FX, [{"countermeasure": "Pedestrian Hybrid Beacons", "what": "a beacon"}], None,
                                 "not stated", lambda c: (seen.append(c), uncontrolled)[1])
    assert seen == ["Uncontrolled"] and a["verdict"] == "proceed_after_site_check"
    assert a["parts"][0]["control_check"]["mapped"] == "signal" and "confirm the control on site" in a["reasons"][0]
    assert review.implied_control("Lighting") is None and review.implied_control("Leading Pedestrian Interval") == "Signalized"


def test_a_kept_objection_submitted_again_is_not_counted_as_dropped(monkeypatch):
    """Independent test round 2: the red team resubmits its kept objections with the replacements, and the memo
    counted them as dropped."""
    rv = _review_with_receipts()
    keep = {"objection": "Backplates would do more", "receipt": "D3",
            "field": "best_alternative.injury_crashes_avoided_per_year", "value": "1.6"}

    def fake_run_agent(client, model, inst, task, tools, *a, **k):
        tools[0].fn(objections=[keep])
        out = tools[0].fn(objections=[keep])
        assert out["kept"] == 1 and out["dropped"] == 0

        class R:
            usd, stopped = 0.004, "finished"
        return R()
    monkeypatch.setattr(review, "run_agent", fake_run_agent)
    assert review.red_team(rv, FakeOpen())["dropped"] == []


def test_the_work_order_names_the_proposal_and_each_parts_verdict():
    """Independent test round 2: a review's letter did not mention the proposal it was the work order for."""
    r = {"corner": "A St & B Ave, Zedburg", "verdict_text": "decide part by part",
         "proposal": {"cost_usd": 45000.0, "cost_covers": "this fix only",
                      "parts": [{"countermeasure": "Rectangular Rapid Flashing Beacons", "what": "two beacons"},
                                {"countermeasure": "other", "what": "curb ramps"}]},
         "appraisal": {"parts": [{"countermeasure": "Rectangular Rapid Flashing Beacons", "verdict_text": "proceed"},
                                 {"countermeasure": "other", "verdict_text": "not covered by the evidence"}]},
         "letter": "Dear colleagues,"}
    w = review.work_requested(r)
    assert "A St & B Ave" in w and "$45,000" in w and "- two beacons: proceed" in w
    assert "- curb ramps: not covered by the evidence" in w
    assert w in review.memo_md({**r, "status": "published", "memo": {}})
