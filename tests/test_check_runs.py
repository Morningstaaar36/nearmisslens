"""T25's scoring: the rule is measured from saved results, and each control by what it was put in to catch."""
import json

from nearmisslens import check, check_runs


def _case(i, status, control=None, usd=0.1, sources=(), verdicts=()):
    return {"id": i, "control": control, "status": status, "cost_usd": {"meta": usd}, "seconds": 100,
            "sources": [{"url": "u", "quote": "q", "quote_check": s} for s in sources],
            "claims": [{"verdict": v} for v in verdicts], "summary": "", "findings": [], "letter": None}


def test_the_rule_and_the_controls_are_scored(monkeypatch):
    sp = check_runs.spec("T25")
    real = [i for i in sp["inputs"] if not i.get("control")]
    cases = [_case(i["id"], "published", sources=["verified"]) for i in real[:8]] + \
            [_case(i["id"], "abstained") for i in real[8:]] + \
            [_case("control_offtopic", "abstained", "offtopic"),
             _case("control_false_claim", "published", "false_claim", sources=["verified"],
                   verdicts=["differs from the record"])]
    s = check_runs.summary({"id": "T25", "cases": cases})
    assert s["published_real"] == 8 and s["verified_share"] == 1.0 and s["rule_met"], s["met"]
    cases[-1]["claims"] = [{"verdict": "consistent with the record"}]  # the false claim passed: the control fails
    cases[-2]["status"] = "published"  # and the off-topic page was published
    s = check_runs.summary({"id": "T25", "cases": cases})
    assert not s["met"]["control_false_claim"] and not s["met"]["control_offtopic"] and not s["rule_met"]


def test_a_run_resumes_and_uses_the_specs_date(monkeypatch, tmp_path):
    monkeypatch.setattr(check_runs, "RESULTS_DIR", tmp_path)
    monkeypatch.setenv("NML_ASOF", "2026-10-31")  # run() sets it; restored after the test
    (tmp_path / "bench").mkdir()
    calls = []
    monkeypatch.setattr(check, "check", lambda text, city, **k: (calls.append(text), {"status": "abstained"})[1])
    res = check_runs.run("T25", None, None)
    assert len(res["cases"]) == len(calls) == 12
    calls.clear()
    assert len(check_runs.run("T25", None, None)["cases"]) == 12 and calls == []  # resumed: nothing ran again
    assert json.loads((tmp_path / "bench" / "experiment_T25.json").read_text())["cases"][0]["id"] == "url_nyc"


def test_every_input_is_valid_for_its_city(monkeypatch):
    from nearmisslens import orchestrator
    monkeypatch.setattr(orchestrator, "public_url", lambda u: u.startswith("https://"))
    for i in check_runs.spec("T25")["inputs"]:
        assert check.validate(i["input"], i["city"], i["kind"]) [0] == i["kind"], i["id"]


def test_the_site_gets_the_saved_checks_with_their_record_notes(monkeypatch, tmp_path):
    from nearmisslens import pages
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "experiment_T25.json").write_text(json.dumps({"id": "T25", "cases": [
        {**_case("url_nyc", "published", sources=["verified"]), "asof": "2026-10-31", "kind": "url", "city": "nyc",
         "input": "https://example.org/a", "letter": "Plate ABC1234 seen."}]}))
    monkeypatch.setattr(check_runs, "RESULTS_DIR", tmp_path)
    out = tmp_path / "site"
    out.mkdir()
    pages.checks_page(out)
    blob = json.loads((out / "checks.json").read_text())
    assert blob["summary"]["by_input"] == {"url_nyc": "published"} and "2026-10-31" in blob["cases"][0]["record_notes"][0]
    assert "ABC1234" not in (out / "checks.json").read_text()  # plates are redacted from what the site publishes


def test_a_saved_letter_that_misses_recorded_deaths_gets_a_correction():
    from nearmisslens import pages
    case = {"letter": "The record shows 14 injury crashes and 0 people killed.",
            "findings": [{"text": "Kilbourn had 14 injury crashes in police records since 2021-10-31: 1 person killed.", "receipt": "D3"}]}
    assert "record holds 1 death" in pages.letter_correction(case)
    assert pages.letter_correction({**case, "letter": "The record shows 1 person killed."}) is None
    assert pages.letter_correction({**case, "findings": [{"text": "14 injury crashes: 0 people killed."}]}) is None
