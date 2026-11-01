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
