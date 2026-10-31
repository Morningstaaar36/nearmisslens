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
