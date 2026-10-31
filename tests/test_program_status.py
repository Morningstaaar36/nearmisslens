from nearmisslens import treatments as T


def _res(city, key, gate, theta, ci, adapter="ds", cm="Thing", naive=-20.0):
    return {"id": "S", "city": city, "spec": {"programs": [{"key": key, "adapter": adapter, "countermeasure": cm}]},
            "gates": {key: {"countermeasure": cm, "treatment": key, "outcome": "pedestrian", "primary": "p",
                            "placebos": [], **gate}},
            "runs": {"p": {"pedestrian": {"theta": theta, "ci95": ci, "sites": 100}}},
            "naive": {key: {"pedestrian": {"change_pct": naive}}}}


def test_status_labels_and_repeat_risk(monkeypatch):
    rs = [_res("x", "a", {"passed": True, "rule_met": True, "placebo_ok": True}, 0.8, [0.7, 0.9], "da", "A"),
          _res("x", "b", {"passed": False, "rule_met": True, "placebo_ok": False}, 0.8, [0.7, 0.9], "db", None, -26),
          _res("x", "c", {"passed": False, "rule_met": False, "placebo_ok": True}, 1.0, [0.9, 1.1], "dc", "C"),
          _res("x", "d", {"passed": False, "rule_met": False, "placebo_ok": True}, 1.3, [1.1, 1.5], "dd", "D")]
    monkeypatch.setattr(T, "results", lambda: rs)
    got = {p["program"]: p["status"] for p in T.programs("x")}
    assert got == {"a": "worked", "b": "earlier trend", "c": "not shown", "d": "worse"}
    assert T.program_status("x", "Nothing")["status"] == "untested"
    assert T.program_status("y", "A")["status"] == "untested"
    texts = " ".join(p["text"] for p in T.programs("x")).lower()
    assert "fail" not in texts and "doesn't work" not in texts and "-26%" in texts
    flags = T.repeat_risk("x", [{"dataset": "db", "year": 2019}, {"dataset": "db", "year": 2017},
                                {"dataset": "da", "year": 2016}, {"dataset": "zz"}])
    assert [(f["dataset"], f["year"]) for f in flags] == [("db", 2017)]


def test_pct_rounds_half_away_from_zero():
    assert T.pct(-32.5) == -33 and T.pct(32.5) == 33 and T.pct(-0.4) == 0
