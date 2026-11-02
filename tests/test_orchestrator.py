import json

from nearmisslens import orchestrator as O
from tests.test_agent import FakeClient, call, usage

REPORT = {"junction": {"name": "Broadway & East Pine Street, Seattle"},
          "receipts": [{"id": "R3", "tool": "choose_fixes"}],
          "findings": {"choose_fixes": {"crashes": {"injury_crashes": 40, "pedestrian_injured": 12}}},
          "claims": [{"text": "40 injury crashes.", "receipt": "R3"}]}


PAGE = "Filler text about the city. " * 60 + "A pedestrian was hit at Broadway and East Pine on Tuesday evening, police said. The driver, 52, stayed."


def _setup(monkeypatch, page=PAGE):
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


def test_unreadable_pages_publish_unverified_and_loaded_pages_must_hold_the_quote(monkeypatch):
    monkeypatch.setattr(O, "page_text", lambda url: "" if "blocked" in url else "x " * 900 + "the pedestrian was hit at the corner")
    assert O.quote_check("The pedestrian was hit at the corner", "https://ok.example") == "verified"
    assert O.quote_check("Three pedestrians died here yesterday", "https://ok.example") == "absent"
    assert O.quote_check("anything at all here", "https://blocked.example") == "unreadable"


def test_address_variants_reach_the_geocoders_format():
    from nearmisslens.brief import address_variants
    v = address_variants("16th St and L St NW, Washington, DC")
    assert "16th Street Northwest & L Street Northwest, Washington, DC" in v
    assert "Aurora Avenue North & North 97th Street, Seattle" in address_variants("Aurora Ave N near N 97th St, Seattle")


def test_gate_names_the_receipt_that_holds_the_numbers(monkeypatch):
    _setup(monkeypatch)
    desk = O.Desk()
    desk.receipt("root_cause", {"patterns": [{"share": 0.3}]})
    desk.receipt("choose_fixes", {"crashes": {"injury_crashes": 40, "pedestrian_injured": 12}})
    desk.final = None
    finish = next(t for t in O.core_tools(desk) if t.name == "finish").fn
    out = finish("A summary.", [{"text": "The corner had 40 injury crashes.", "receipt": "D1"}], [])
    assert "cite D2" in " ".join(out["errors"])


def _tools(monkeypatch, *receipts, pages=None):
    _setup(monkeypatch)
    desk = O.Desk("seattle")
    for tool, data in receipts:
        desk.receipt(tool, data)
    desk.pages.update(pages or {})
    desk.final = None
    return desk, {t.name: t.fn for t in O.core_tools(desk)}


SRC = [{"url": "https://news.example/x", "quote": "A pedestrian was hit at Broadway and East Pine"}]
CRASHES = ("choose_fixes", {"crashes": {"injury_crashes": 40, "pedestrian_injured": 12}})


def test_the_receipt_hint_is_never_offered_for_a_finding_without_numbers(monkeypatch):
    desk, t = _tools(monkeypatch, ("root_cause", {"patterns": []}),
                     ("choose_fixes", {"options": [{"countermeasure": "Leading Pedestrian Interval",
                                                    "evidence": "needs a site check", "verify_on_site": "signal"}]}))
    out = t["check_findings"]("s", [{"text": "Add a Leading Pedestrian Interval here.", "receipt": "D1"}], SRC)
    probs = " ".join(out["problems"])
    assert "cite D" not in probs and "site check" in probs  # the site-check rule holds whichever receipt is cited


def test_source_facts_are_checked_against_the_page_and_record_numbers_against_receipts(monkeypatch):
    desk, t = _tools(monkeypatch, CRASHES)
    ok = [{"text": "The driver was 52.", "receipt": "https://news.example/x"},
          {"text": "The corner had 40 injury crashes.", "receipt": "D1"},
          {"text": "12 pedestrians were injured there.", "receipt": "D1"},
          {"text": "The record shows 40 injury crashes at the corner.", "receipt": "D1"}]
    assert t["check_findings"]("s", ok, SRC)["would_publish"]
    bad = [{**ok[0], "text": "The driver was 61."}] + ok[1:]
    assert "61 is not on the page" in " ".join(t["check_findings"]("s", bad, SRC)["problems"])


def test_years_do_not_count_as_record_numbers_and_one_quote_must_be_verified(monkeypatch):
    desk, t = _tools(monkeypatch, CRASHES)
    f = [{"text": f"In {y} the city painted the crosswalk.", "receipt": "D1"} for y in (2019, 2020, 2021)]
    probs = " ".join(t["check_findings"]("s", f, [{"url": "https://blocked.example", "quote": "x" * 20}])["problems"])
    assert "only 0 findings give a number" in probs and "no quote could be checked" in probs


def test_claim_verdicts_are_receipts_and_findings_must_state_them(monkeypatch):
    desk, t = _tools(monkeypatch, CRASHES)
    r = t["check_claim"]("There were 45 injury crashes at the corner.", "D1")
    assert r["verdict"] == "differs from the record" and "within" in r["record_frame"]
    r2 = t["check_claim"]("The victim was 30 years old.", "D1")
    assert r2["verdict"] == "cannot be checked against this record"
    base = [{"text": "The corner had 40 injury crashes.", "receipt": "D1"},
            {"text": "12 pedestrians were injured there.", "receipt": "D1"},
            {"text": "The record shows 40 injury crashes at the corner.", "receipt": "D1"}]
    wrong = base + [{"text": "The report's 45 injury crashes is consistent with the record.", "receipt": r["receipt"]}]
    assert "check found" in " ".join(t["check_findings"]("s", wrong, SRC)["problems"])
    right = base + [{"text": "The report's 45 injury crashes differs from the record.", "receipt": r["receipt"]}]
    assert t["check_findings"]("s", right, SRC)["would_publish"]


def test_claim_checks_are_capped(monkeypatch):
    desk, t = _tools(monkeypatch, CRASHES)
    for _ in range(O.MAX_CLAIM_CHECKS):
        assert "verdict" in t["check_claim"]("40 injury crashes.", "D1")
    assert "error" in t["check_claim"]("40 injury crashes.", "D1")


def test_read_page_returns_the_text_the_gate_checks(monkeypatch):
    desk, t = _tools(monkeypatch)
    out = t["read_page"]("https://news.example/x", "pedestrian Pine")
    assert out["readable"] and "A pedestrian was hit at Broadway and East Pine" in out["text"]
    monkeypatch.setattr(O, "page_text", lambda url: "")
    assert t["read_page"]("https://blocked.example", "x")["readable"] is False


def test_a_record_handed_to_the_desk_is_a_verifiable_source(monkeypatch):
    rec = {"https://city.example/requests/1.json": "Street defect: deep pothole in the crosswalk at 5th & Main"}
    desk, t = _tools(monkeypatch, pages=rec)
    assert O.quote_check("deep pothole in the crosswalk", "https://city.example/requests/1.json", desk.pages) == "verified"


def test_program_names_match_by_their_words_and_the_city_by_name(monkeypatch):
    progs = [{"countermeasure": "Leading Pedestrian Interval", "label": "LPI signals", "status": "worked", "sites": 9},
             {"countermeasure": None, "label": "speed humps", "status": "not shown", "sites": 5}]
    monkeypatch.setattr(O.treatments, "programs", lambda city: progs if city == "seattle" else [])
    assert O.program_match("Seattle", "leading pedestrian intervals")["status"] == "worked"
    assert O.program_match("seattle", "LPI")["status"] == "worked"
    miss = O.program_match("seattle", "Vision Zero")
    assert miss["status"] == "untested" and "speed humps" in miss["programs_with_studies"]


def test_an_address_snaps_to_the_nearest_screened_corner_or_is_refused(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(O.brief if hasattr(O, "brief") else __import__("nearmisslens.brief", fromlist=["x"]),
                        "geocode", lambda a: (47.6, -122.3, a))
    corner = {"name": "Broadway & East Pine Street", "lat": 47.6005, "lon": -122.3}
    monkeypatch.setattr(O, "nearest_corner", lambda city, lat, lon: (corner, O.context.metres(lat, lon, corner["lat"], corner["lon"])))
    seen = {}
    monkeypatch.setattr(O.engineer, "investigate", lambda desk, q, name, lat, lon, letter_client=None:
                        seen.setdefault("r", {**REPORT, "junction": {"name": name}}))
    desk, t = _tools(monkeypatch)
    out = t["investigate"]("1600 Broadway, Seattle", False)
    assert out["snapped"]["to"] == "Broadway & East Pine Street" and out["snapped"]["metres"] < O.SNAP_M
    corner["lat"] = 47.61  # about 1.1 km away: refused, with the reason
    desk, t = _tools(monkeypatch)
    assert "not an intersection" in t["investigate"]("George's Repair Shop, Seattle", False)["error"]


def test_the_desk_stays_on_one_intersection(monkeypatch):
    desk, t = _tools(monkeypatch)
    t["investigate"]("Broadway & E Pine, Seattle", False)
    other = {**REPORT, "junction": {"name": "Aurora Avenue North & North 97th Street, Seattle"}}
    monkeypatch.setattr(O.engineer, "plan", lambda address, letter_client=None: other)
    assert "stay on one intersection" in t["investigate"]("Aurora Ave N & N 97th St, Seattle", False)["error"]


def test_only_public_web_addresses_are_fetched():
    assert not O.public_url("http://127.0.0.1/x") and not O.public_url("http://169.254.169.254/latest")
    assert not O.public_url("javascript:alert(1)") and not O.public_url("file:///etc/passwd")


def test_a_photo_is_never_fetched_in_replay(monkeypatch):
    monkeypatch.setattr(O.context, "_cache_dir", lambda: __import__("pathlib").Path("/nonexistent-cache"))
    from nearmisslens.config import SETTINGS
    monkeypatch.setattr(SETTINGS, "replay", True)
    assert O.image_bytes("https://example.com/a.jpg") is None


def test_the_model_read_check_flags_but_never_decides_a_verdict(monkeypatch):
    desk, t = _tools(monkeypatch, CRASHES)
    monkeypatch.setattr(O.engineer, "model_read_errors", lambda text, data, client: ["model-read check: no field x"])
    r = t["check_claim"]("The corner had 40 injury crashes.", "D1")
    assert r["verdict"] == "consistent with the record" and r["model_read_flags"]


def test_licence_plates_are_never_published(monkeypatch):
    assert O.has_plate("Blue Mazda mx5 with CA plate 7ABC123 blocking driveway")
    assert not O.has_plate("The plate glass window at 1600 Broadway") and not O.has_plate("a licence to operate")
    assert "7ABC123" not in O.redact("with CA plate 7ABC123 blocking")
    desk, t = _tools(monkeypatch, CRASHES)
    out = t["check_findings"]("s", [{"text": "A car with plate 7ABC123 blocked it.", "receipt": "D1"}], SRC)
    assert "licence plate" in " ".join(out["problems"])
