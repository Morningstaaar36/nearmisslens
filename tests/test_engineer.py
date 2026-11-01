from nearmisslens import engineer as E

CR = {"source": "Test crashes", "since": "2021-10-31", "crashes": 40, "injury_crashes": 20, "pedestrian_injured": 6,
      "cyclist_injured": 1, "pedestrian_killed": 0}
FX = {"options": [{"countermeasure": "Backplates", "scale": "low-cost", "expected_crashes_avoided_per_year": 1.2,
                   "cmf_id": "1410", "chosen_by": "the record FHWA's fact sheet cites", "harm_avoided_usd_per_year": 410000.0,
                   "targets": "all injury crashes", "break_even_cost_usd": 2880000.0, "verify_on_site": None}],
      "not_estimated": [], "control": "Signalized", "harm": {"usd_per_year": 1369600.0}, "repeat_risk": []}
WHO = {"owners": [{"party": "the state DOT", "roads": ["Main Expressway (I 95)"], "confidence": "recorded",
                   "basis": {"dataset": "Test inventory (layer 0)"}}],
       "requesters": [{"party": "Council District 1", "role": "council", "basis": {"dataset": "Test districts"}}],
       "summary": "the state DOT (Main Expressway (I 95))"}


def _fake(monkeypatch):
    d = {"lat": 1.0, "lon": 2.0, "city": "t", "crashes": CR, "plans": {"projects": []}, "street": {}}
    monkeypatch.setattr(E.brief, "geocode", lambda q: (1.0, 2.0, "Main St & Oak Ave, Testville"))
    monkeypatch.setattr(E.citywide, "cities", lambda: ["t"])
    monkeypatch.setattr(E.context, "dossier", lambda lat, lon: d)
    monkeypatch.setattr(E.rootcause, "analyse", lambda lat, lon: {
        "source": "Test crashes", "crashes": 40, "enough_crashes": True, "not_recorded": [],
        "over_represented": [{"pattern": "vehicle: truck", "phrase": "involved a truck", "share": 0.3, "city_share": 0.1}]})
    monkeypatch.setattr(E.treatments, "programs", lambda city: [
        {"label": "speed humps", "status": "not shown", "text": "at 50 sites the change could be zero",
         "source": "NML-Bench S"}])
    monkeypatch.setattr(E.brief, "fix_options", lambda d, cmf: FX)
    monkeypatch.setattr(E.jurisdiction, "who_must_act", lambda lat, lon, streets, layout=None: WHO)


def test_plan_every_claim_has_a_receipt_and_passes_the_checker(monkeypatch):
    _fake(monkeypatch)
    r = E.plan("Main St & Oak Ave")
    assert r["claim_errors"] == []
    ids = {x["id"] for x in r["receipts"]}
    assert r["claims"] and all(c["receipt"] in ids for c in r["claims"])
    assert {x["tool"] for x in r["receipts"]} == {"root_cause", "test_programs", "choose_fixes", "who_must_act",
                                                  "draft_request"}
    text = " ".join(c["text"] for c in r["claims"])
    assert "30% of crashes here involved a truck" in text and "The state DOT is responsible" in text
    assert all(x["sources"] for x in r["receipts"] if x["tool"] != "draft_request")


def test_finish_gate_refuses_wrong_labels_and_missing_receipts(monkeypatch):
    _fake(monkeypatch)
    desk = E.Desk()
    _, rid = E.choose_fixes(desk, 1.0, 2.0)
    _, rid2 = E.root_cause(desk, 1.0, 2.0)
    ok = [{"text": "6 pedestrians injured here.", "receipt": rid}]
    assert E.check_claims(ok, desk) == []
    assert E.check_claims([{"text": "6 pedestrians were killed.", "receipt": rid}], desk)
    assert E.check_claims([{"text": "20 injury crashes.", "receipt": "R99"}], desk)
    assert E.check_claims([{"text": "45% involved a truck.", "receipt": rid2}], desk)  # the record says 30%
    assert E.check_claims([{"text": "30% involved a truck.", "receipt": rid2}], desk) == []
    assert E.check_claims(ok, desk, ("who_must_act",)) == ["no claim cites who_must_act"]


def test_overclaiming_words_are_refused(monkeypatch):
    _fake(monkeypatch)
    desk = E.Desk()
    _, rid = E.test_programs(desk, 1.0, 2.0)
    assert E.check_claims([{"text": "Speed humps failed here.", "receipt": rid}], desk)
    assert E.check_claims([{"text": "Trucks caused these crashes.", "receipt": rid}], desk)
    assert E.check_claims([{"text": "Speed humps: not shown.", "receipt": rid}], desk) == []
    assert E.wording("had \u201cfailure to yield\u201d recorded as a contributing factor") == []
    assert E.check_summary("No program failed.", desk) and E.check_summary("Speed humps were not shown.", desk) == []


def test_text_report_and_agent_entry_point_exist(monkeypatch):
    _fake(monkeypatch)
    r = E.plan("Main St & Oak Ave")
    out = E.text(r)
    assert "Receipts:" in out and "R1" in out and callable(E.run) and "finish" in E.INSTRUCTIONS


def test_street_numbers_in_the_corner_name_are_not_counts(monkeypatch):
    _fake(monkeypatch)
    monkeypatch.setattr(E.brief, "geocode", lambda q: (1.0, 2.0, "Avenue C & East 138 Street, Testville"))
    r = E.plan("Avenue C & East 138 Street")
    assert r["claim_errors"] == [] and "East 138 Street" in r["claims"][0]["text"]
    assert E.recheck(r)["claim_errors"] == []
    bad = {**r, "claims": [{**r["claims"][0], "text": "East 138 Street had 999 injury crashes."}]}
    assert E.recheck(bad)["claim_errors"]


def test_receipt_ids_are_never_reused_after_a_receipt_is_removed():
    from nearmisslens.engineer import _next_rid
    assert _next_rid([{"id": "R1"}, {"id": "R2"}, {"id": "R7"}]) == "R8"
    assert _next_rid([]) == "R1"


def test_a_percentage_must_be_a_share_or_change_not_any_number_in_the_record():
    from nearmisslens.context import FactCheck
    fc = FactCheck({"injury_crashes": 129, "pedestrian_share": 0.277, "theta": 0.833, "ci95": [0.781, 0.887]})
    assert fc.text("28% of crashes had a pedestrian hurt.") == []
    assert fc.text("Crashes fell 17% (95% interval 11% to 22%).") == []
    assert fc.text("Crashes rose 129%.")  # 129 is a count, not a share
    assert fc.text("Crashes fell 40%.")


def test_causal_wording_beyond_caused_is_refused():
    for s in ("the trucks led to the crashes", "crashes due to speeding", "this fix will prevent all of them",
              "the program is proven"):
        assert E.wording(s), s
    assert not E.wording("NYSDOT is responsible for the expressway; the program worked.")


def test_placeholder_install_dates_are_not_years():
    from nearmisslens.opendata import known_year
    assert known_year(1899) is None and known_year(None) is None and known_year(2015) == 2015


def test_agent_mode_keeps_each_refused_attempt_with_its_reasons(monkeypatch):
    from tests.test_agent import FakeClient, call, usage
    _fake(monkeypatch)
    loc = {"lat": 1.0, "lon": 2.0}
    script = [call("locate", {"address": "Main St & Oak Ave"}, "c1"), call("root_cause", loc, "c2"),
              call("test_programs", loc, "c3"), call("choose_fixes", loc, "c4"),
              call("who_must_act", {**loc, "name": "Main St & Oak Ave"}, "c5")]
    bad = call("finish", {"summary": "6 pedestrians were killed here.", "claims": [
        {"text": "Main St & Oak Ave had 6 pedestrians killed.", "receipt": "R3"}]}, "c6")
    good = call("finish", {"summary": "6 pedestrians were injured here.", "claims": [
        {"text": "Main St & Oak Ave had 20 injury crashes, with 6 pedestrians injured.", "receipt": "R3"},
        {"text": "30% of crashes involved a truck.", "receipt": "R1"},
        {"text": "The city's speed humps: not shown.", "receipt": "R2"},
        {"text": "The state DOT is responsible for Main Expressway (I 95).", "receipt": "R4"}]}, "c7")
    fc = FakeClient([{"id": f"r{k}", "output": [c], "usage": usage()} for k, c in enumerate(script + [bad, good])])
    rep = E.run("Investigate Main St & Oak Ave", fc, budget_usd=5.0)
    assert len(rep["refused_attempts"]) == 1
    assert any("killed" in e or "deaths" in e for e in rep["refused_attempts"][0]["errors"])
    assert rep["claims"] and not rep["claim_errors"]


def test_a_fix_that_needs_a_site_check_cannot_be_stated_as_supported_outright():
    data = {"options": [{"countermeasure": "Yellow Change Intervals", "evidence": "needs a site check",
                         "verify_on_site": "the current yellow plus all-red time is below the ITE recommended practice"}]}
    assert E.conditional_fix_errors("Fixes the record supports include Yellow Change Intervals.", data)
    assert not E.conditional_fix_errors("Yellow Change Intervals, if a timing check confirms it.", data)
    assert not E.conditional_fix_errors("Backplates with Retroreflective Borders.", data)
