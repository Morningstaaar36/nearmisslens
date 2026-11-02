import json

from nearmisslens import orchestrator as O
from tests.test_agent import FakeClient, call, usage

REPORT = {"junction": {"name": "Broadway & East Pine Street, Seattle"},
          "receipts": [{"id": "R3", "tool": "choose_fixes"}],
          "findings": {"choose_fixes": {"crashes": {"injury_crashes": 40, "pedestrian_injured": 12}}},
          "claims": [{"text": "40 injury crashes.", "receipt": "R3"}]}


def _setup(monkeypatch, page="A pedestrian was hit at Broadway and East Pine on Tuesday evening, police said."):
    monkeypatch.setattr(O.engineer, "plan", lambda address, letter_client=None: REPORT)
    monkeypatch.setattr(O, "page_text", lambda url: page)
    monkeypatch.setattr(O, "dataset_tools", lambda city, desk: (None, []))


def _finish(findings, sources):
    return call("finish", {"summary": "A crash was reported at this corner.", "findings": findings, "sources": sources}, "f")


def test_a_case_runs_from_source_to_published_findings(monkeypatch):
    _setup(monkeypatch)
    fc = FakeClient([
        {"id": "1", "output": [call("investigate", {"address": "Broadway & E Pine, Seattle", "draft_letter": False}, "a")], "usage": usage()},
        {"id": "2", "output": [_finish([{"text": "The corner had 40 injury crashes.", "receipt": "D1"},
                                        {"text": "12 pedestrians were injured there.", "receipt": "D1"},
                                        {"text": "The record shows 40 injury crashes at the corner.", "receipt": "D1"}],
                                       [{"url": "https://news.example/x", "quote": "A pedestrian was hit at Broadway and East Pine"}])], "usage": usage()}])
    out = O.run_case("A news story about Broadway & E Pine", "seattle", fc)
    assert out["finished"] and out["refusals"] == 0 and out["corner"].startswith("Broadway")


def test_publish_gate_refuses_a_quote_not_in_the_page_and_a_wrong_number(monkeypatch):
    _setup(monkeypatch)
    bad = _finish([{"text": "The corner had 45 injury crashes.", "receipt": "D1"}],
                  [{"url": "https://news.example/x", "quote": "Three pedestrians were killed at the corner"}])
    fc = FakeClient([
        {"id": "1", "output": [call("investigate", {"address": "Broadway & E Pine, Seattle", "draft_letter": False}, "a")], "usage": usage()},
        {"id": "2", "output": [bad], "usage": usage()}, {"id": "3", "output": [bad], "usage": usage()},
        {"id": "4", "output": [bad], "usage": usage()}])
    out = O.run_case("A news story", "seattle", fc)
    assert not out["finished"] and out["stopped"] == "escalated"
    errs = json.dumps([s["error"] for s in out["trace"] if s["error"]])
    assert "refused by the publish gate" in errs


def test_quote_matching_ignores_punctuation_and_case():
    assert O._norm("Hit at “Broadway”, E. Pine!") == "hit at broadway e pine"
