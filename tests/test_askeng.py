import json

from nearmisslens import askeng
from tests.test_agent import FakeClient, call, usage

REPORT = {"junction": {"name": "Main St & Oak Ave, Testville"},
          "receipts": [{"id": "R1", "tool": "choose_fixes", "summary": "s", "sources": ["x"], "checks": [], "seconds": 0}],
          "findings": {"choose_fixes": {"crashes": {"injury_crashes": 20, "pedestrian_injured": 6}}}}


def test_answer_claims_must_match_receipts_and_refusals_are_returned(monkeypatch):
    monkeypatch.setattr(askeng, "_report", lambda city, slug: REPORT)
    fc = FakeClient([
        {"id": "r1", "output": [call("read_receipt", {"receipt": "R1"}, "c1")], "usage": usage()},
        {"id": "r2", "output": [call("finish", {"answer": "Busy corner.", "claims": [
            {"text": "6 pedestrians were killed here.", "receipt": "R1"}]}, "c2")], "usage": usage()},
        {"id": "r3", "output": [call("finish", {"answer": "Busy corner.", "claims": [
            {"text": "6 pedestrians were injured here.", "receipt": "R1"}]}, "c3")], "usage": usage()},
    ])
    out = askeng.ask("t", "main_st_oak_ave", "How many pedestrians were hurt?", fc)
    assert out["claims"] == [{"text": "6 pedestrians were injured here.", "receipt": "R1"}]
    assert out["refused"] and "killed" in out["refused"][0]["text"]
    sent = json.dumps(fc.payloads[1]["input"])
    assert "pedestrian_injured" in sent  # the receipt's data reached the model


def test_t17_questions_have_expected_values_and_scoring_works():
    from nearmisslens import askbench
    rep = {"findings": {"choose_fixes": {"crashes": {"pedestrian_injured": 7}, "options": [{"countermeasure": "Backplates with Retroreflective Borders"}]},
                        "who_must_act": {"owners": [{"party": "the State DOT (SDOT), Region 1", "roads": ["Main Expressway (I 9)"]}]},
                        "test_programs": {"programs": [{"label": "LPI signals", "status": "worked"}, {"label": "speed humps", "status": "not shown"}]},
                        "root_cause": {"over_represented": [{"pattern": "vehicle: truck or bus", "phrase": "involved a truck or bus"}]}}}
    qs = askbench.questions(rep, 0)
    assert [q["kind"] for q in qs] == ["answerable", "answerable", "unanswerable", "adversarial"]
    assert qs[0]["expect"] == ["7"] and "truck or bus caused" in qs[3]["q"]
    assert askbench.correct(qs[0], {"claims": [{"text": "7 pedestrians were injured."}]})
    assert not askbench.correct(qs[3], {"claims": [{"text": "Trucks caused these crashes."}]})
    assert askbench.correct({"kind": "unanswerable"}, {"claims": [{"text": "The record has no traffic counts."}]})
