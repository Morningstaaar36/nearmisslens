import json

import numpy as np
import pandas as pd

from nearmisslens import export
from tests.test_audit import junction


def test_event_window_keeps_nearby_users_relative_to_the_event():
    st = junction(1)
    st["frame"] = np.round(st["t"] * 10).astype(int)
    ev = {"t": 5.0, "id_1": "a0", "id_2": "b0", "measure": "PET", "value": 0.5}
    w = export.event_window(st, ev, 0.0, 0.0)
    ids = {u["id"] for u in w["users"]}
    assert {"a0", "b0"} <= ids and w["measure"] == "PET"
    times = [p[0] for u in w["users"] for p in u["track"]]
    assert min(times) >= export.WINDOW_S[0] - 1e-9 and max(times) <= export.WINDOW_S[1] + 1e-9
    far = export.event_window(st, ev, 500.0, 500.0)
    assert far["users"] == []


def test_signal_entry_counts_states_per_approach_and_class():
    st = junction(2)
    signals = pd.DataFrame({"direction": ["W", "S"], "turn": ["s", "l"], "begin_time": [0, 0],
                            "end_time": [1000, 1000], "state": ["G", "r"]})
    rows = export.signal_entry(st, signals)
    by = {(r["arm"], r["cls"]): r for r in rows}
    assert by[("W", "vehicle")]["G"] == 2 and by[("S", "vehicle")]["r"] == 2


def test_selftest_rows_parse_the_report(tmp_path):
    p = tmp_path / "SELFTEST.md"
    p.write_text("| Check | Status | Criterion | Result |\n|---|---|---|---|\n"
                 '| routes | PASS | accuracy >= 0.9 | `{"a": 0.95}` |\n')
    assert export.selftest_rows(p) == [{"check": "routes", "status": "PASS", "criterion": "accuracy >= 0.9",
                                        "result": {"a": 0.95}}]
    assert export.selftest_rows(tmp_path / "missing.md") == []


def test_panel_view_keeps_caught_claims(tmp_path):
    p = tmp_path / "panel.json"
    p.write_text(json.dumps({"status": "complete", "memo": "m", "stages": [
        {"role": "judge", "model": "w", "accepted": True, "stopped": "finish_tool", "turns": 2, "usd": 0.1,
         "rejected_attempts": [{"arguments": {}, "errors": ["memo: number 9.9 does not appear"]}],
         "decision_log": []}]}))
    v = export.panel_view(p)
    assert v["stages"][0]["caught"] == ["memo: number 9.9 does not appear"] and "decision_log" not in v["stages"][0]
    assert export.panel_view(tmp_path / "none.json") is None
