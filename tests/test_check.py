"""nml check: any input and any registry city through the desk, with a fake desk run (no model, no network)."""
import json

import pytest

from nearmisslens import check, opendata


def fake_run(finished=True):
    seen = {}

    def run(task, city, client, letter_client=None, model_check_client=None, budget_usd=0.5, max_turns=22, pages=None,
            max_reads=None, sources_name_corner=False, required_source=None, claims_from_sources=False,
            keep_receipt_data=False):
        seen.update(task=task, city=city, pages=pages, letter=letter_client, max_reads=max_reads,
                    corner_rule=sources_name_corner, required=required_source)
        final = {"summary": "Two crashes; plate ABC1234 seen.", "findings": [{"receipt": "D1", "text": "A finding."}],
                 "sources": [{"url": "input:text", "quote": "a quote", "quote_check": "verified"}]} if finished else None
        return {"finished": finished, "final": final, "stopped": "finish_tool" if finished else "max_turns", "turns": 5,
                "usd": 0.11, "trace": [{"errors": ["source 0: the quote is not in the page"]}],
                "receipts": {"D2": {"tool": "check_claim", "data": {"claim": "c", "verdict": "differs from the record",
                                                                    "frame": "100 m"}}},
                "corner": "A Street & B Avenue", "asof": "2026-11-02", "letter": "Dear X,"}
    return run, seen


@pytest.fixture
def fake_city(tmp_path, monkeypatch):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"adapters": [{"id": "zz-crashes", "kind": "crash", "city": "zz"}],
                               "cities": [{"id": "zz", "name": "Zedburg", "bbox": [1, 1, 2, 2], "agency": "the ZDOT"},
                                          {"id": "yy", "name": "Whyton", "bbox": [3, 3, 4, 4], "agency": "the YDOT"}]}))
    monkeypatch.setattr(opendata, "REGISTRY", reg)
    monkeypatch.setattr(check.orchestrator, "public_url", lambda u: u.startswith("https://"))  # no DNS in tests


def test_a_url_runs_the_desk_on_that_page_in_the_registry_city(fake_city, tmp_path):
    run, seen = fake_run()
    r = check.check("https://example.org/story", "zz", runner=run, out_dir=tmp_path / "out")
    assert r["status"] == "published" and r["kind"] == "url" and seen["city"] == "zz"
    assert "https://example.org/story" in seen["task"] and "Zedburg" in seen["task"]
    assert r["claims"] == [{"id": "D2", "claim": "c", "verdict": "differs from the record", "frame": "100 m"}]
    assert "ABC1234" not in r["summary"]  # plates are redacted
    md = (tmp_path / "out" / "report.md").read_text()
    assert "differs from the record" in md and "A finding. [D1]" in md
    assert json.loads((tmp_path / "out" / "result.json").read_text())["status"] == "published"


def test_a_source_text_is_handed_to_the_desk_and_cited_by_its_id(fake_city, tmp_path):
    run, seen = fake_run()
    check.check("The council says the corner had 12 crashes.", "zz", kind="source", runner=run, out_dir=tmp_path)
    assert seen["pages"] == {check.SOURCE_ID: "The council says the corner had 12 crashes."}
    assert check.SOURCE_ID in seen["task"]


def test_a_claim_without_a_link_is_found_and_a_report_names_its_place(fake_city, tmp_path):
    run, seen = fake_run()
    assert check.check("Ten people were hurt at the corner last year", "zz", runner=run, out_dir=tmp_path)["kind"] == "find"
    assert "Find a published source" in seen["task"]
    check.check("Cars run the red light every morning", "zz", kind="report", address="1st & Main",
                photo="https://example.org/p.jpg", runner=run, out_dir=tmp_path)
    assert "at 1st & Main, Zedburg" in seen["task"] and "photo: https://example.org/p.jpg" in seen["task"]


def test_unsupported_cities_get_a_plain_answer_and_no_run(fake_city):
    run, seen = fake_run()
    r = check.check("https://example.org/story", "yy", runner=run)
    assert r["status"] == "unsupported_city" and "no crash data" in r["reason"] and not seen
    assert "not a city in the registry" in check.check("x", "nowhere", runner=run)["reason"]


def test_an_unfinished_case_is_abstained_with_the_gates_reason(fake_city, tmp_path):
    run, _ = fake_run(finished=False)
    r = check.check("https://example.org/story", "zz", runner=run, out_dir=tmp_path)
    assert r["status"] == "abstained" and "max_turns" in r["reason"] and "quote is not in the page" in r["reason"]
    assert r["trace"] and "the last refusal" in r["reason"]


def test_bad_inputs_are_refused_before_any_run(fake_city):
    run, seen = fake_run()
    with pytest.raises(ValueError):
        check.check("", "zz", runner=run)
    with pytest.raises(ValueError):
        check.check("http://127.0.0.1/admin", "zz", runner=run)
    with pytest.raises(ValueError):
        check.check("x" * (check.MAX_INPUT + 1), "zz", runner=run)
    assert not seen


def test_a_failed_run_is_an_error_never_published(fake_city):
    def boom(*a, **k):
        raise RuntimeError("network down")
    assert check.check("https://example.org/story", "zz", runner=boom)["status"] == "error"


def test_city_list_says_what_each_supports(fake_city):
    rows = {c["id"]: c for c in check.cities()}
    assert rows["zz"]["checkable"] and not rows["yy"]["checkable"] and "crash" in rows["yy"]["missing"]


def test_reading_is_capped_so_a_case_reaches_its_findings():
    from nearmisslens import orchestrator
    desk = orchestrator.Desk("zz")
    desk.pages = {f"input:{k}": "Some text about a corner." * 5 for k in range(3)}
    read = next(t for t in orchestrator.core_tools(desk, max_reads=2) if t.name == "read_page")
    assert "text" in read.fn("input:0", "corner") and "text" in read.fn("input:1", "corner")
    assert "2 pages read already" in read.fn("input:2", "corner")["error"]
    unlimited = next(t for t in orchestrator.core_tools(orchestrator.Desk("zz")) if t.name == "read_page")
    assert all("error" not in unlimited.fn("input:9", "x") for _ in range(10))  # registered runs are unchanged


def test_check_runs_cap_their_reading(fake_city, tmp_path):
    run, seen = fake_run()
    check.check("https://example.org/story", "zz", runner=run, out_dir=tmp_path)
    assert seen["max_reads"] == check.MAX_READS and seen["corner_rule"]


def test_a_source_must_name_the_corners_street():
    from nearmisslens.orchestrator import names_corner
    corner = "8th Street Southeast & Pennsylvania Avenue Southeast, Zedburg"
    assert names_corner("A crash at Pennsylvania Ave SE and 8th St left one dead.", corner)
    assert names_corner("Police closed 8th Street after the crash.", corner)
    assert not names_corner("A cyclist was hit near Rhode Island Ave NW in Logan Circle.", corner)
    assert not names_corner("A crash on 18th Street.", corner)  # '8th' must be a word of its own


def test_the_record_date_is_stated_and_a_death_the_record_lacks_is_flagged():
    base = {"status": "published", "asof": "2026-10-31", "summary": "",
            "sources": [{"quote": "A pedestrian was struck and killed at the corner on Tuesday."}],
            "letter": "The record shows 12 injury crashes; no one was killed."}
    notes = check.record_lag(base)
    assert "2026-10-31" in notes[0] and len(notes) == 2 and "not what happened on the street" in notes[1]
    assert len(check.record_lag({**base, "letter": "The record shows 12 injury crashes and 1 death."})) == 1
    assert len(check.record_lag({**base, "status": "abstained"})) == 1
    assert "About the record's date" in check.report_md({**base, "record_notes": notes, "kind": "url", "input": "x"})


def test_a_check_must_cite_its_own_input(fake_city, tmp_path):
    """T25's false-claim control: the desk read "text" for "input:text", found nothing, and published a case about
    another corner from another page. A check now must cite the input it was given."""
    run, seen = fake_run()
    check.check("https://example.org/story", "zz", runner=run, out_dir=tmp_path / "a")
    assert seen["required"] == "https://example.org/story"
    check.check("The agency says this corner had no crashes.", "zz", kind="source", runner=run, out_dir=tmp_path / "b")
    assert seen["required"] == check.SOURCE_ID
    check.check("A claim to find.", "zz", kind="find", runner=run, out_dir=tmp_path / "c")
    assert seen["required"] is None  # a claim to find has no page of its own


def test_a_mistyped_input_id_reads_the_one_text_handed_in_and_the_gate_wants_it_cited():
    from nearmisslens import orchestrator
    desk = orchestrator.Desk("zz")
    desk.pages = {"input:text": "The agency said that First Street and Main Street had zero injury crashes."}
    ts = {t.name: t for t in orchestrator.core_tools(desk, required_source="input:text")}
    assert "zero injury crashes" in ts["read_page"].fn("text", "crashes")["text"]
    other = ts["check_findings"].fn(summary="s", findings=[], sources=[{"url": "https://example.org/x", "quote": "q"}])
    assert any("must cite the input it was given" in e for e in other["problems"])
    own = ts["check_findings"].fn(summary="s", findings=[], sources=[
        {"url": "input:text", "quote": "First Street and Main Street had zero injury crashes"}])
    assert not any("must cite the input" in e for e in own["problems"])
    assert orchestrator._same_url("https://www.example.org/a/", "http://example.org/a")


def test_a_claim_must_be_the_sources_not_the_desks_own_record_sentence():
    """Independent test: a check graded its own count ('48 injury crashes', in no source) as a source claim,
    'consistent'. With claims_from_sources every number in a claim must be on a page the desk read."""
    from nearmisslens import orchestrator
    desk = orchestrator.Desk("zz")
    desk.pages = {"input:text": "A pedestrian was killed at First Street and Main Street on Tuesday; 3 others were hurt."}
    desk.receipts["D1"] = {"tool": "choose_fixes", "data": {"crashes": {"injury_crashes": 48}}}
    ts = {t.name: t for t in orchestrator.core_tools(desk, claims_from_sources=True)}
    own = ts["check_claim"].fn(text="First Street and Main Street had 48 injury crashes.", receipt="D1")
    assert "48 is not on any page you read" in own["error"]
    assert "error" not in ts["check_claim"].fn(text="3 others were hurt.", receipt="D1")
    plain = {t.name: t for t in orchestrator.core_tools(orchestrator.Desk("zz"))}  # registered runs: unchanged
    assert "not on any page" not in str(plain["check_claim"].fn(text="48 injury crashes.", receipt="D9"))


def test_a_case_cannot_say_a_letter_was_drafted_when_none_was():
    from nearmisslens import orchestrator
    desk = orchestrator.Desk("zz")
    desk.report = {"junction": {"name": "A & B"}, "findings": {"draft_request": {"letter": None}}}
    ts = {t.name: t for t in orchestrator.core_tools(desk, claims_from_sources=True)}
    out = ts["check_findings"].fn(summary="A request letter to the city is drafted and checked.", findings=[], sources=[])
    assert any("no letter was drafted" in e for e in out["problems"])
    assert orchestrator.LETTER_SAID.search("The letter was drafted.") and not orchestrator.LETTER_SAID.search("A letter is ready to draft from these facts.")


def test_every_receipt_is_saved_for_audit(fake_city, tmp_path):
    def run(task, city, client, **k):
        assert k["keep_receipt_data"] and k["claims_from_sources"]
        return {"finished": True, "final": {"summary": "s", "findings": [], "sources": []}, "stopped": "finish_tool",
                "turns": 3, "usd": 0.01, "trace": [], "receipts": {"D1": {"tool": "choose_fixes"}},
                "receipts_data": {"D1": {"tool": "choose_fixes", "data": {"crashes": {"injury_crashes": 48}}}}}
    out = check.check("https://example.org/story", "zz", runner=run, out_dir=tmp_path / "r")
    import json as _j
    assert _j.loads((tmp_path / "r" / "receipts.json").read_text())["D1"]["data"]["crashes"]["injury_crashes"] == 48
    assert out["receipts_file"].endswith("receipts.json")


def test_a_published_check_quotes_the_sentence_that_names_its_corner(monkeypatch):
    """Independent test: four verified quotes, none naming the intersection. One must."""
    from nearmisslens import orchestrator
    desk = orchestrator.Desk("zz")
    desk.pages = {"https://example.org/a": "A woman was struck by a car. Police were called to First Street and Main Street."}
    desk.report = {"junction": {"name": "First Street & Main Street, Zedburg"}, "findings": {}}
    ts = {t.name: t for t in orchestrator.core_tools(desk, sources_name_corner=True)}
    bad = ts["check_findings"].fn(summary="s", findings=[], sources=[{"url": "https://example.org/a", "quote": "A woman was struck by a car."}])
    assert any("no quote names" in e for e in bad["problems"])
    good = ts["check_findings"].fn(summary="s", findings=[], sources=[
        {"url": "https://example.org/a", "quote": "Police were called to First Street and Main Street."}])
    assert not any("no quote names" in e for e in good["problems"])
