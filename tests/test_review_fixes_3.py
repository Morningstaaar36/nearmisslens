"""Fixes from the Nov 2 code review: replay never reaches the network or rewrites results, checks fail loudly,
Corner Watch's absent and exposure rules, cut answers are never cached."""
import json

import pytest

from nearmisslens import corner_watch as W
from nearmisslens import desk_runs, engineer, inbox, openclient
from nearmisslens.cache import Cache, ReplayMiss, atomic_write
from nearmisslens.segments import Detection


def _spec(tmp_path, monkeypatch, cases):
    exp = tmp_path / "validation" / "experiments"
    exp.mkdir(parents=True)
    (exp / "TX.json").write_text(json.dumps({"id": "TX", "budget_usd": 0.3, "max_turns": 9, "cases": cases}))
    monkeypatch.setattr(desk_runs, "ROOT", tmp_path)
    (tmp_path / "bench").mkdir()
    monkeypatch.setattr(desk_runs, "RESULTS_DIR", tmp_path)


def test_a_desk_run_takes_its_limits_from_the_spec_and_resumes(tmp_path, monkeypatch):
    cases = [{"kind": "news", "city": "nyc", "task": "a"}, {"kind": "news", "city": "nyc", "task": "b"}]
    _spec(tmp_path, monkeypatch, cases)
    seen = []

    def run_case(task, city, client, letter_client=None, model_check_client=None, pages=None, **kw):
        seen.append((task, kw))
        return {"task": task, "finished": True}
    monkeypatch.setattr(desk_runs.orchestrator, "run_case", run_case)
    desk_runs.run_desk("TX", None, None)
    assert seen == [("a", {"budget_usd": 0.3, "max_turns": 9}), ("b", {"budget_usd": 0.3, "max_turns": 9})]
    desk_runs.run_desk("TX", None, None)  # resumed: nothing runs again
    assert len(seen) == 2


def test_a_replay_miss_stops_the_run_and_is_never_recorded(tmp_path, monkeypatch):
    _spec(tmp_path, monkeypatch, [{"kind": "news", "city": "nyc", "task": "a"}])

    def miss(*a, **k):
        raise ReplayMiss("agent/xx")
    monkeypatch.setattr(desk_runs.orchestrator, "run_case", miss)
    with pytest.raises(ReplayMiss):
        desk_runs.run_desk("TX", None, None)
    assert not (tmp_path / "bench" / "experiment_TX.json").exists()


def test_an_inbox_snapshot_is_read_by_its_date(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.SETTINGS, "data_dir", tmp_path)
    d = tmp_path / "inbox" / "x"
    d.mkdir(parents=True)
    (d / "2026-11-01.json").write_text('[{"a": 1}]')
    (d / "2026-11-02.json").write_text('[{"a": 2}]')
    assert inbox.fetch({"id": "x"}, date="2026-11-01") == [{"a": 1}]
    with pytest.raises(FileNotFoundError):
        inbox.fetch({"id": "x"}, date="2026-10-01")


def test_a_failed_model_check_is_reported_not_passed(monkeypatch):
    from nearmisslens import claimcheck

    def boom(*a, **k):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(claimcheck, "parse", boom)
    assert engineer.model_read_errors("40 crashes.", {}, object()) == ["model-read check unavailable (RuntimeError)"]

    def miss(*a, **k):
        raise ReplayMiss("x")
    monkeypatch.setattr(claimcheck, "parse", miss)
    assert engineer.model_read_errors("40 crashes.", {}, object()) == []


def test_a_claim_citing_an_unknown_receipt_is_set_apart():
    agent = {"receipts": [{"id": "R1", "tool": "choose_fixes"}],
             "claims": [{"text": "40 injury crashes.", "receipt": "R9"}]}
    current = {"junction": {"name": "A & B, City"}, "findings": {"choose_fixes": {"crashes": {"injury_crashes": 40}}}}
    keep, gone = engineer.recheck_agent(agent, current)
    assert not keep and "cites no receipt" in gone[0]["errors"][0]


def test_absent_needs_sam_to_find_nothing_too(monkeypatch):
    near = Detection(0, "1", "curb extension", 100, 100, 200, 150, None, 0.9)
    assert W.confirm({"answer": "absent", "points": []}, [near]) == "unsure"
    assert W.confirm({"answer": "absent", "points": []}, []) == "absent"


def test_a_corner_where_nobody_was_seen_gets_no_exposure_rate(monkeypatch, tmp_path):
    monkeypatch.setattr(W.cameras, "adapter", lambda city: {"id": "cams"})
    monkeypatch.setattr(W, "frames", lambda cam, a: [tmp_path / f"{cam}.jpg"])
    monkeypatch.setattr(W, "daylight", lambda paths: paths)
    monkeypatch.setattr(W, "count_video", lambda c, cam, paths, concept, work: [0] if cam == "empty" or concept == "car" else [30])
    monkeypatch.setattr(W, "count_image", lambda c, p, concept: 0)
    monkeypatch.setattr(W, "look", lambda c, p: {})
    monkeypatch.setattr(W.cv2, "imread", lambda p: None)
    out = W.watch(None, "seattle", [{"id": "empty", "injury_crashes": 50}, {"id": "busy", "injury_crashes": 20}],
                  sample_images=0)
    rows = {r["id"]: r for r in out["rows"]}
    assert rows["empty"]["injury_crashes_per_1000_people_seen"] is None and "rank_by_exposure" not in rows["empty"]
    assert rows["busy"]["rank_by_exposure"] == 1


def test_a_cut_open_weights_answer_is_never_cached(tmp_path):
    resp = openclient.from_chat({"choices": [{"message": {"content": "Dear"}, "finish_reason": "length"}], "usage": {}})
    assert resp["status"] == "incomplete"
    oc = openclient.OpenWeightsClient.__new__(openclient.OpenWeightsClient)
    oc.cache, oc.base_url, oc.model, oc.force_finish_after = Cache(tmp_path), "x", "m", 6
    oc.ledger, oc.spent, oc.price = tmp_path / "ledger.jsonl", 0.0, None
    with pytest.raises(openclient.IncompleteResponse):
        oc.cached("letter", {"q": 1}, lambda: resp, None, 0, "letter", require_text=True)
    assert not list(tmp_path.rglob("*.json.gz"))


def test_atomic_writes_leave_no_temporary_files(tmp_path):
    atomic_write(tmp_path / "a.json", "{}")
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
