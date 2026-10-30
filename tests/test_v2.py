import json

import numpy as np
import pandas as pd

from nearmisslens import agent, ask, complaints, tracks
from nearmisslens.agent import Tool, run_agent
from tests.test_agent import FakeClient, call, usage
from tests.test_panel import MEMO, cmf_db, facts


def _track(n=200, v=8.0, noise=0.3, seed=0):
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"id": "a", "frame": t, "x": 5 + v * t / 10 + rng.normal(0, noise, n),
                         "y": 2 + rng.normal(0, noise, n), "cls": "vehicle", "length": 4.5, "width": 1.8, "axis": 0.0})


def test_kalman_recovers_velocity_rejects_spike_and_bridges_gap():
    pts = _track()
    pts.loc[50, "x"] += 30
    pts = pts[~pts["frame"].between(100, 107)]
    st = tracks.kalman_states(pts, 10.0)
    assert len(st) == 200 and set(range(100, 108)) <= set(st["frame"])
    assert abs(st["vx"].median() - 8.0) < 0.2 and st["vx"].between(7.0, 9.0).all()


def test_kalman_restarts_after_identity_jump_and_splits_long_gaps():
    pts = _track()
    pts.loc[pts["frame"] >= 120, "y"] += 40          # another road user takes over the id
    st = tracks.kalman_states(pts, 10.0, tracks.Kinematics(reset_after=5))
    assert st["vy"].abs().max() < 5.0                 # no 40 m jump turned into a velocity
    gap = _track()
    gap = gap[~gap["frame"].between(80, 120)]
    assert not set(range(81, 120)) & set(tracks.kalman_states(gap, 10.0)["frame"])


def test_size_bias_is_applied_per_class():
    k = tracks.Kinematics(size_bias_m=(("vehicle", (0.1, 0.2)),))
    st = tracks.kalman_states(_track(), 10.0, k)
    assert np.isclose(st["length"].iloc[0], 4.6) and np.isclose(st["width"].iloc[0], 2.0)


def test_tool_results_can_carry_images(tmp_path):
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG fake")
    out = agent.tool_output({"rank": 1, agent.MEDIA_KEY: [str(img)]})
    assert out[0]["type"] == "input_text" and agent.MEDIA_KEY not in out[0]["text"]
    assert out[1]["type"] == "input_image" and out[1]["image_url"].startswith("data:image/png;base64,")
    assert agent.tool_output({"rank": 1}) == '{"rank": 1}'


def test_agent_escalates_after_repeated_refusals_and_keeps_summaries():
    refuse = Tool("finish", "stop", {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                  lambda: {"error": "rejected"})
    thought = {"type": "reasoning", "summary": [{"type": "summary_text", "text": "checking hotspot 1"}],
               "encrypted_content": "e"}
    fc = FakeClient([{"id": f"r{i}", "output": [thought, call("finish", {}, f"c{i}")], "usage": usage()}
                     for i in range(5)])
    run = run_agent(fc, "muse-wonder-1.0", "x", "t", [refuse], max_turns=5, budget_usd=1.0, summaries=True,
                    escalate_after=3)
    assert run.stopped == "escalated" and run.refusals == 3 and run.turns == 3
    assert fc.payloads[0]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert run.thoughts[0]["text"] == "checking hotspot 1"
    assert [e["kind"] for e in run.timeline()[:2]] == ["thought", "tool"]


def test_intake_checker_rejects_wrong_users_unkept_cmf_and_invented_numbers(tmp_path):
    record = []
    ts, _ = ask.tools(facts(), MEMO, cmf_db(), tmp_path, record=record)
    finish = next(t for t in ts if t.name == "finish").fn
    ok = finish(verdict="supported", rank=1, road_users=["vehicle"], cmf_ids=["1447"],
                answer="Hotspot 1 shows 12 conflicts between vehicles.")
    assert ok == {"ok": True}
    bad = finish(verdict="supported", rank=1, road_users=["pedestrian", "vehicle"], cmf_ids=["4096"],
                 answer="Hotspot 1 had 99 crashes.")
    errs = " ".join(bad["errors"])
    assert "dominant conflicts are vehicle and vehicle" in errs and "CMF 4096" in errs and "number 99" in errs
    assert finish(verdict="not_observed", rank=1, road_users=[], cmf_ids=[], answer="no")["errors"]
    assert len(record) == 3


def test_intake_without_checker_accepts_but_records_errors(tmp_path):
    record = []
    ts, _ = ask.tools(facts(), MEMO, cmf_db(), tmp_path, checked=False, record=record)
    finish = next(t for t in ts if t.name == "finish").fn
    assert finish(verdict="supported", rank=7, road_users=["vehicle"], cmf_ids=[], answer="x") == {"ok": True}
    assert record[0]["errors"]


def test_benchmark_complaints_have_expected_verdicts():
    f = facts()
    f["findings"][0]["dominant"].update({"movements": {"left": 4}, "approaches": {"W": 4}})
    cs = complaints.benchmark_set(f)
    by_kind = {}
    for c in cs:
        by_kind.setdefault(c["kind"], []).append(ask.truth(c, f))
    assert by_kind["full"][0] == ("supported", {1}) and by_kind["users_only"][0] == ("supported", {1})
    assert by_kind["other_approach"][0] == ("not_observed", set())
    assert all(v == ("not_observed", set()) for v in by_kind["absent_pair"])
    assert all(v == ("unclear", set()) for v in by_kind["vague"])
    assert len({c["text"] for c in cs}) == len(cs)


def test_scout_point_prompt_and_coverage():
    from nearmisslens import scout
    from nearmisslens.segments import Detection
    p = scout.point_prompt([(10.4, 20.6), (30, 40)], 1984, 1144)
    assert p == "<0f>1<|point;x=10;y=21;w=1984;h=1144|>,2<|point;x=30;y=40;w=1984;h=1144|>"
    d = Detection(frame=0, obj="1", concept="scooter", x1=0, y1=0, x2=50, y2=50, mask=None, score=None)
    assert scout._covered([d], 52, 10) and not scout._covered([d], 80, 80)
    assert scout._match(np.array([[0, 0], [100, 100]]), np.array([[3, 4], [500, 500]]), 25) == 1


def test_office_requires_signoff_and_grounded_work_order(tmp_path, monkeypatch):
    from nearmisslens import office
    monkeypatch.setattr(office.ask, "load", lambda name, runs: (facts(), MEMO))
    monkeypatch.setattr(office.SETTINGS, "runs_dir", tmp_path)
    good = {"work_order": "Hotspot 1: 12 conflicts; install CMF 1447.", "cmf_ids": ["1447"], "ranks": [1]}
    fc = FakeClient([
        {"id": "r1", "output": [call("finish", good, "c1")], "usage": usage()},
        {"id": "r2", "output": [call("request_signoff", {"summary": "backplates at hotspot 1"}, "c2")], "usage": usage()},
        {"id": "r3", "output": [call("finish", {**good, "work_order": "Hotspot 1 had 77 crashes."}, "c3")], "usage": usage()},
        {"id": "r4", "output": [call("finish", good, "c4")], "usage": usage()}])
    out = office.run(fc, "test_sam", [], cmf_db(), signoff=lambda s: {"approved": True, "by": "tester"})
    assert out["stopped"] == "finish_tool" and out["work_order"]["cmf_ids"] == ["1447"]
    errs = [e for a in out["rejected_attempts"] for e in a["errors"]]
    assert any("request_signoff" in e for e in errs) and any("number 77" in e for e in errs)
    assert out["signoffs"][0]["by"] == "tester" and out["refusals"] == 2


def test_checker_reads_decimal_commas():
    from nearmisslens import panel
    g = panel.Grounding(facts(), MEMO)
    assert g.text("El punto 1 tiene 164,4 por 1000 usuarios.") == []
    assert g.text("1,234 road users") != []  # thousands separator, not in the data


def test_checker_keeps_comma_lists():
    from nearmisslens import panel
    f = facts()
    f["findings"].append({**f["findings"][0], "rank": 2})
    g = panel.Grounding(f, MEMO)
    assert g.text("Hotspots 1,2 share 12 conflicts each.") == []


def test_reseed_prompt_and_duplicates():
    from nearmisslens import reseed
    from nearmisslens.segments import Detection
    assert reseed.box_prompt([(1.6, 2, 30, 40)], 50, 1984, 1144) == "<50f>1<|box;x1=1;y1=2;x2=30;y2=40;w=1984;h=1144|>"
    D = lambda f, o, x: Detection(frame=f, obj=o, concept="scooter", x1=x, y1=0, x2=x + 10, y2=10, mask=None, score=None)
    old = [D(f, "t0:1", 0) for f in range(4)]
    new = [D(f, "t0:r0:1", 1) for f in range(4)] + [D(f, "t0:r0:2", 100) for f in range(4)]
    assert reseed.duplicates(new, old) == {"t0:r0:1"}
    assert reseed._covered(old, D(0, "x", 3)) and not reseed._covered(old, D(0, "x", 100))


def test_reseed_boxes_are_clamped_inside_the_frame():
    from nearmisslens import reseed
    assert reseed.box_prompt([(233, 1105, 254, 1144)], 0, 1984, 1144).endswith("x2=254;y2=1143;w=1984;h=1144|>")


def test_open_client_translates_agent_turns_both_ways(tmp_path):
    from nearmisslens import openclient
    payload = {"instructions": "be brief", "max_output_tokens": 100, "reasoning": {"effort": "low"},
               "tools": [{"type": "function", "name": "finish", "description": "d", "parameters": {"type": "object"}}],
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
                         {"type": "reasoning", "encrypted_content": "x", "summary": []},
                         {"type": "function_call", "call_id": "c1", "name": "evidence", "arguments": "{}"},
                         {"type": "function_call_output", "call_id": "c1",
                          "output": [{"type": "input_text", "text": "{}"}, {"type": "input_image", "image_url": "data:x"}]}]}
    body = openclient.to_chat(payload)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"] and body["tool_choice"] == "required"
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "evidence"
    resp = openclient.from_chat({"choices": [{"message": {"reasoning_content": "think", "content": None,
        "tool_calls": [{"id": "t1", "function": {"name": "finish", "arguments": "{\"a\": 1}"}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    assert [o["type"] for o in resp["output"]] == ["reasoning", "function_call"] and resp["usage"]["input_tokens"] == 10


def test_fusion_nb_fit_recovers_parameters_and_eb_shrinks():
    from nearmisslens import fusion
    rng = np.random.default_rng(1)
    x = rng.poisson(3, 4000)
    X = np.column_stack([np.ones(len(x)), np.log1p(x)])
    mu = np.exp(-0.5 + 0.8 * np.log1p(x))
    phi = 2.0
    y = rng.negative_binomial(phi, phi / (phi + mu))
    beta, phi_hat = fusion.fit_nb(X, y.astype(float))
    assert abs(beta[0] + 0.5) < 0.15 and abs(beta[1] - 0.8) < 0.1 and abs(phi_hat - 2.0) < 0.5
    assert fusion._top(np.array([3, 2, 1, 0.]), np.array([3, 2, 1, 0.]), 0.5) == 1.0


def test_open_data_dates_parse_common_formats():
    from nearmisslens import opendata
    import datetime as dt
    assert opendata._date("2020-01-02T00:00:00.000") == dt.date(2020, 1, 2)
    assert opendata._date("1/2/2020 12:00:00 AM") == dt.date(2020, 1, 2)
    assert opendata._date(1577923200000) == dt.date(2020, 1, 2)
    assert opendata._date("not a date") is None
