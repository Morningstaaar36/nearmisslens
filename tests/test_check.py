"""nml check: any input and any registry city through the desk, with a fake desk run (no model, no network)."""
import json

import pytest

from nearmisslens import check, opendata


def fake_run(finished=True):
    seen = {}

    def run(task, city, client, letter_client=None, model_check_client=None, budget_usd=0.5, max_turns=22, pages=None,
            max_reads=None, sources_name_corner=False):
        seen.update(task=task, city=city, pages=pages, letter=letter_client, max_reads=max_reads,
                    corner_rule=sources_name_corner)
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
