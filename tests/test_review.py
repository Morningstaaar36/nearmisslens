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
    ("Roundabouts", None, "reconsider"),  # no evidence fits the site
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
    rv.appraisal = review.appraise(FX, "Leading Pedestrian Interval", 15000.0)
    rv.desk.receipt("appraisal", rv.appraisal)
    return rv


def test_the_red_team_keeps_only_objections_whose_fact_checks_out(monkeypatch):
    rv = _review_with_receipts()

    def fake_run_agent(client, model, inst, task, tools, *a, **k):
        res = tools[0].fn(objections=[
            {"objection": "Backplates would do more", "receipt": "D3", "field": "best_alternative.injury_crashes_avoided_per_year", "value": "1.6"},
            {"objection": "The evidence is weak", "receipt": "D2", "field": "options.0.evidence", "value": "national studies"},
            {"objection": "No such receipt", "receipt": "D9", "field": "x", "value": "1"}])
        assert res["ok"] and res["kept"] == 1 and res["dropped"] == 2

        class R:
            usd, stopped = 0.004, "finished"
        return R()
    monkeypatch.setattr(review, "run_agent", fake_run_agent)
    out = review.red_team(rv, FakeOpen())
    assert [o["id"] for o in out["kept"]] == ["O1"] and out["kept"][0]["value"] == 1.6
    assert "holds 'FHWA-cited'" in out["dropped"][0]["why"] and rv.red_team_usd == 0.004


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
    assert ts["check_memo"].fn(summary="Compare before committing.", verdict=v, findings=good, answers=ans)["would_publish"]
    bad_verdict = ts["finish"].fn(summary="Go ahead.", verdict="proceed", findings=good, answers=ans)
    assert "the verdict is the appraisal's" in " ".join(bad_verdict["errors"])
    unanswered = ts["finish"].fn(summary="Compare.", verdict=v, findings=good, answers=[])
    assert any("O1" in e for e in unanswered["errors"])
    wrong_number = ts["finish"].fn(summary="Compare.", verdict=v, answers=ans,
                                   findings=good[:2] + [{"text": "It is expected to avoid 4.2 injury crashes a year.", "receipt": "D3"}])
    assert "error" in wrong_number and rv.final is None
    assert ts["finish"].fn(summary="Compare before committing.", verdict=v, findings=good, answers=ans) == {"ok": True}
    assert rv.final["verdict"] == v


def test_the_proposal_must_name_a_federal_countermeasure():
    rv = review.Review("zz")
    ts = {t.name: t for t in review.tools(rv, None, None, None)}
    assert "error" in ts["register_proposal"].fn(address="A & B", countermeasure="Magic paint", cost_usd=0, goal="x")
    ok = ts["register_proposal"].fn(address="A & B", countermeasure="Lighting", cost_usd=0, goal="x")
    assert ok["receipt"] == "D1" and rv.proposal["cost_usd"] is None
    assert "error" in ts["appraise"].fn()  # nothing investigated yet


def test_an_unsupported_city_gets_a_plain_answer():
    assert review.review("LPI at A & B", "atlantis")["status"] == "unsupported_city"


def test_the_test_set_is_real_split_and_place_free_in_code():
    import json
    rows = json.loads(review.EXAMPLES.read_text())["proposals"]
    assert {r["split"] for r in rows} == {"registered", "team", "held_out"}
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
