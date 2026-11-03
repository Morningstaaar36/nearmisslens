"""A town inside a city's bounding box is not the city: a case there is refused, and the desk cannot move to the
city's own corner with the same street names (independent test round 2, the suburb trap). No network."""
from nearmisslens import brief, orchestrator

CITY = {"id": "zz", "name": "Zedburg", "short_name": "Zedburg", "aliases": ["Zed City"], "bbox": [0, 0, 1, 1]}


def test_places_after_in_skip_the_citys_own_names_and_dates():
    text = "A crash at Main St & Oak Ave in Elmwood in June; another in Zedburg's centre and one in Zed City."
    assert brief.places_named(text, CITY) == ["Elmwood"]


def test_a_county_named_after_the_city_is_not_the_city():
    assert not brief.in_city_limits("Elmwood, Zedburg County, Statia, United States", CITY)
    assert brief.in_city_limits("Old Quarter, Zedburg, Zedburg County, Statia, 12345, United States", CITY)


def test_a_town_outside_the_limits_is_found(monkeypatch):
    monkeypatch.setattr(brief, "place_outside", lambda name, city: "Elmwood, Statia" if name == "Elmwood" else None)
    assert brief.towns_outside("A project at Main St & Oak Ave in Elmwood, in Old Quarter.", CITY) == \
        [("Elmwood", "Elmwood, Statia")]


def _desk(monkeypatch):
    from nearmisslens import opendata
    monkeypatch.setattr(opendata, "city", lambda cid: CITY if cid == "zz" else None)
    desk = orchestrator.Desk("zz")
    desk.report = {"junction": {"name": "West Main Street & North Oak Avenue, Zedburg"}, "findings": {}}
    return desk


def test_the_gate_refuses_a_case_whose_input_places_it_in_another_town(monkeypatch):
    monkeypatch.setattr(brief, "place_outside", lambda name, city: "Elmwood, Statia" if name == "Elmwood" else None)
    desk = _desk(monkeypatch)
    desk.task = "Check this input: A pedestrian safety project at Main Street & Oak Avenue in Elmwood"
    errs = orchestrator._outside_errors(desk, [])
    assert errs and "Elmwood" in errs[0] and "Do not publish" in errs[0]
    desk.task = "Check this input: A pedestrian safety project at Main Street & Oak Avenue in Old Quarter"
    assert orchestrator._outside_errors(desk, []) == []


def test_a_refused_town_address_stays_refused_for_the_same_street_names(monkeypatch):
    monkeypatch.setattr(brief, "place_outside", lambda name, city: None)
    desk = _desk(monkeypatch)
    desk.outside.append("Main Street & Oak Avenue, Elmwood")
    assert "only shares its street names" in orchestrator._outside_errors(desk, [])[0]
    inv = {t.name: t for t in orchestrator.core_tools(desk)}["investigate"]
    out = inv.fn(address="W Main St & N Oak Ave, Zedburg", draft_letter=False)
    assert "not the one the input is about" in out["error"]


def test_same_corner_lives_in_brief_and_review_still_uses_it():
    from nearmisslens import review
    assert review.same_corner is brief.same_corner
    assert brief.same_corner("Main Street & Oak Avenue, Elmwood", "W Main St & N Oak Ave, Zedburg")


def test_a_place_after_a_comma_is_checked_too():
    assert brief.places_named("A beacon at Main Street & Oak Avenue, Elmwood, part of a $360,000 project", CITY) == \
        ["Elmwood"]
