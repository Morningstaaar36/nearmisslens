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
    assert T.pct(100 * (0.675 - 1)) == -33 and T.pct(-32.5) == -33 and T.pct(32.5) == 33 and T.pct(-0.4) == 0


def test_one_entry_per_program_registered_study_first(monkeypatch):
    from nearmisslens import treatments as T
    rows = [{"city": "x", "study": "auto_x", "program": "a", "countermeasure": "LPI", "outcome": "pedestrian",
             "sites": 366, "status": "worked", "label": "leading pedestrian intervals"},
            {"city": "x", "study": "T13_x", "program": "b", "countermeasure": "LPI", "outcome": "pedestrian",
             "sites": 371, "status": "worked", "label": "LPI signals"}]
    monkeypatch.setattr(T, "programs", lambda city=None: rows)
    out = T.distinct_programs("x")
    assert len(out) == 1 and out[0]["study"] == "T13_x" and out[0]["also_tested"][0]["sites"] == 366


def test_flag_fields_use_registry_labels_and_bare_codes_are_skipped():
    from nearmisslens import rootcause as R
    a = {"factor_fields": ["HITPARKEDCAR"], "crash_type_fields": ["CODE", "DESC"], "labels": {"HITPARKEDCAR": "hit a parked car"}}
    tags, _ = R.profile([{"HITPARKEDCAR": "Y", "CODE": "32", "DESC": "Rear Ended"}], a)[0:2]
    assert "factor: hit a parked car" in tags and "crash type: rear ended" in tags
    assert not any(t.endswith(": 32") for t in tags)
