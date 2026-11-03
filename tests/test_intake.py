"""Program intake: Muse Spark lists the projects on an agency's pages; code keeps one only when its passage is on the
page word for word and names both streets, and a cost only when the passage states it (no model, no network)."""
from nearmisslens import intake

PAGE = ("Safe Routes projects. Push button crossing beacon and curb ramps at S Elm St and 13th Ave S leading to the "
        "high school (expected in summer 2026). Mark crosswalks at Park Ave S/S Hamlet St next to the high school "
        "(completed in 2025). A $45,000 curb bulb at Oak St & 3rd Ave (expected 2026). Corridor repaving on Main St.")
PAGES = {"https://agency.example/srts": PAGE}


def _x(**k):
    base = {"page": "https://agency.example/srts", "status": "planned or proposed", "cost_usd": None,
            "cost_covers": "not stated", "treatment_says": None}
    return {**base, **k}


def test_a_project_is_kept_only_when_its_passage_is_on_the_page_and_names_both_streets():
    ok = _x(intersection="S Elm St & 13th Ave S", treatment="crossing beacon and curb ramps",
            source_says="Push button crossing beacon and curb ramps at S Elm St and 13th Ave S")
    assert intake.check_project(ok, PAGES) is None
    assert "word for word" in intake.check_project({**ok, "source_says": "A beacon at S Elm St and 13th Ave S is planned"}, PAGES)
    assert "does not name" in intake.check_project({**ok, "intersection": "S Elm St & 14th Ave S"}, PAGES)
    assert "streets joined" in intake.check_project({**ok, "intersection": "Main St"}, PAGES)
    assert "no page" in intake.check_project({**ok, "page": "https://other.example"}, PAGES)


def _fake(submissions):
    def run_agent(client, model, inst, task, tools, *a, **k):
        for sub in submissions:
            tools[0].fn(projects=sub)

        class R:
            usd = 0.012
        return R()
    return run_agent


def test_extract_keeps_checked_projects_drops_completed_and_unstated_costs(monkeypatch):
    good = _x(intersection="S Elm St & 13th Ave S", treatment="crossing beacon and curb ramps",
              source_says="Push button crossing beacon and curb ramps at S Elm St and 13th Ave S")
    done = _x(intersection="Park Ave S & S Hamlet St", treatment="marked crosswalks", status="completed",
              source_says="Mark crosswalks at Park Ave S/S Hamlet St next to the high school (completed in 2025)")
    costed = _x(intersection="Oak St & 3rd Ave", treatment="a curb bulb", cost_usd=45000, cost_covers="this fix only",
                source_says="A $45,000 curb bulb at Oak St & 3rd Ave (expected 2026)")
    wrong_cost = {**good, "cost_usd": 99000, "cost_covers": "this fix only"}
    bad = _x(intersection="Main St & 1st Ave", treatment="repaving", source_says="Corridor repaving on Main St.")
    monkeypatch.setattr(intake, "run_agent", _fake([[wrong_cost, done, costed, bad], [good]]))
    out = intake.extract([], "Zedburg", None, pages=PAGES)
    texts = [x["text"] for x in out["projects"]]
    assert texts == ["Crossing beacon and curb ramps at S Elm St & 13th Ave S",
                     "A curb bulb at Oak St & 3rd Ave, $45,000 (this fix only)"]
    assert out["projects"][0].get("cost_dropped")  # 99,000 is not in its passage: dropped, not guessed
    assert out["completed_left_out"] == 1
    assert [r["intersection"] for r in out["refused"]] == ["Main St & 1st Ave"] and out["usd"] == 0.012


def test_an_unreadable_page_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(intake.orchestrator, "text_of", lambda url, known=None: None)
    out = intake.extract(["https://refuses.example/list"], "Zedburg", None)
    assert out == {"projects": [], "refused": [], "unreadable": ["https://refuses.example/list"], "usd": 0.0, "pages": []}


def test_a_saved_page_or_text_file_can_be_read(tmp_path):
    f = tmp_path / "agenda.html"
    f.write_text("<html><script>x()</script><p>Curb bulbs at Oak St &amp; 3rd Ave</p></html>")
    pages, bad = intake.read_pages([str(f)])
    assert bad == [] and "Curb bulbs at Oak St" in pages["file:agenda.html"] and "x()" not in pages["file:agenda.html"]


def test_a_location_list_rests_on_the_list_item_and_the_description_of_the_work():
    """T30: a page that lists its locations under one description of the work had no project kept."""
    pages = {"https://agency.example/c35": "The project will upgrade traffic signals with larger signal heads. "
                                           "Project Locations 6th Avenue & Irving Street 25th Avenue & Clement Street"}
    x = {"page": "https://agency.example/c35", "intersection": "6th Avenue & Irving Street",
         "treatment": "signal upgrade", "source_says": "Project Locations 6th Avenue & Irving Street",
         "treatment_says": "The project will upgrade traffic signals with larger signal heads."}
    assert intake.check_project(x, pages) is None
    assert "treatment_says" in intake.check_project({**x, "treatment_says": "New signals everywhere."}, pages)


def test_a_junction_of_three_streets_is_kept():
    """Independent test round 3: junctions where three streets meet were silently left out."""
    pages = {"https://agency.example/c66": "Project Locations: Castro St/Divisadero St/Waller St. New traffic signals will be installed."}
    x = {"page": "https://agency.example/c66", "intersection": "Castro St & Divisadero St & Waller St",
         "treatment": "new traffic signals", "source_says": "Project Locations: Castro St/Divisadero St/Waller St.",
         "treatment_says": "New traffic signals will be installed."}
    assert intake.check_project(x, pages) is None
