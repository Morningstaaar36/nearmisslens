"""The offline geocode table answers only in the city the address names (verifier1 A2)."""
import inspect
import json

import pytest

from nearmisslens import brief

TABLE = {"nyc|3 avenue & broadway": {"lat": 40.73, "lon": -73.99, "name": "Broadway & 3 Avenue", "city": "nyc"},
         "seattle|3 avenue & broadway": {"lat": 47.60, "lon": -122.33, "name": "Broadway & 3 Avenue", "city": "seattle"},
         "sf|4 street & market street": {"lat": 37.78, "lon": -122.40, "name": "Market Street & 4 Street", "city": "sf"}}


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(brief, "gazetteer", lambda: dict(TABLE))

    def refuse(address):
        raise ValueError(f"would look up {address!r}")
    monkeypatch.setattr(brief, "_lookup", refuse)


def test_the_same_street_pair_in_two_cities_gives_two_points(offline):
    ny = brief.geocode("Broadway & 3 Avenue, Brooklyn, NY")
    sea = brief.geocode("Broadway & 3 Avenue, Seattle, WA")
    assert ny[:2] == (40.73, -73.99) and sea[:2] == (47.60, -122.33)
    assert sea[2].endswith("Seattle, WA")


def test_a_city_the_registry_does_not_know_never_gets_another_citys_point(offline):
    with pytest.raises(ValueError, match="would look up"):
        brief.geocode("Broadway & 3 Avenue, Portland, OR")


def test_no_city_is_refused_when_the_corner_is_in_several_and_used_when_in_one(offline):
    with pytest.raises(ValueError, match="more than one city"):
        brief.geocode("Broadway & 3 Avenue")
    assert brief.geocode("4 Street & Market Street")[:2] == (37.78, -122.40)


def test_the_city_named_first_wins():
    assert brief.city_named("Pine St & 5th Ave, Seattle, Washington") == "seattle"
    assert brief.city_named("H St & 7th St NW, Washington, DC") == "dc"
    assert brief.city_named("Bowery & Kenmare St, Manhattan") == "nyc"
    assert brief.city_named("Main St & 1st Ave, Portland, OR") is None
    assert brief.city_named("Main St & 1st Ave") is None


def test_a_lookup_found_in_another_city_is_refused(monkeypatch):
    def fetch(url, params=None, data=None, **k):
        if data:  # the intersection search
            return {"elements": [{"type": "node", "lat": 40.71, "lon": -74.0}]}, None
        if params.get("bounded"):  # the search within the named city (Seattle) finds nothing
            return [], None
        return [{"lat": "40.7", "lon": "-74.0", "display_name": "x"}], None
    monkeypatch.setattr(brief.context, "fetch", fetch)
    monkeypatch.setattr(brief, "GEOCODES", None)  # nothing may be written
    with pytest.raises(ValueError, match="not in the city the address names"):
        brief._lookup("Pike St & 5th Ave, Seattle")


def test_every_saved_entry_is_keyed_by_its_own_city():
    for k, v in brief.gazetteer().items():
        assert k.split("|", 1)[0] == v["city"], k


def test_mined_mechanisms_and_photo_readings_stay_in_their_city():
    from nearmisslens import engineer, miner
    res = {"spec": {**miner.SPEC, "city": "nyc"}, "runs": [{"corner": "broadway_3_avenue", "null": False, "arm": "grid",
                                                         "confirmed": []}]}
    assert miner.corner_mechanisms("broadway_3_avenue", res=res, ds={"corners": []}, city="seattle") == []
    assert engineer.site_check(engineer.Desk(), "bruckner_boulevard_hunts_point_avenue", "seattle") is None
    assert engineer.site_check(engineer.Desk(), "bruckner_boulevard_hunts_point_avenue", "nyc") is not None


def test_no_filler_addressee_and_no_assumed_modes():
    from nearmisslens import engineer, letter
    assert letter._salutation([]) == "To the road owner (not identified in the city's open records),"
    assert not letter._records({"injury_crashes": 3}, "pedestrian")
    assert engineer.crash_sentence("A & B", {"injury_crashes": 3, "since": "2021-10-30", "pedestrian_injured": 2}) == \
        "A & B had 3 injury crashes in police records since 2021-10-30."


def test_a_failed_source_marks_the_report_partial_and_says_so():
    from nearmisslens import engineer
    desk = engineer.Desk()
    desk.dossiers[(1.0, 2.0)] = {"street": {"error": "RuntimeError: Overpass unavailable"}, "crashes": {"crashes": 1}}
    rep = engineer._report("q", "A & B", 1.0, 2.0, desk, [], 0.0, "deterministic")
    assert rep["partial"] and rep["failed_sources"] == ["street: RuntimeError: Overpass unavailable"]
    assert engineer.text({**rep, "source": "saved"}).splitlines()[:2] == [
        f"SAVED REPORT (records as of {rep['asof']}), not a live run.",
        "PARTIAL: these sources could not be read, so the findings below leave them out: "
        "street: RuntimeError: Overpass unavailable"]


def test_a_new_city_is_data_and_its_gaps_are_listed(tmp_path, monkeypatch):
    import json
    from nearmisslens import opendata
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"adapters": [{"id": "x-crashes", "kind": "crash", "city": "x"}], "cities": []}))
    monkeypatch.setattr(opendata, "REGISTRY", reg)
    assert opendata.coverage("x")["city"] is None
    opendata.save_city({"id": "x", "name": "Xville", "bbox": [1, 1, 2, 2], "agency": "the X DOT", "short_name": "Xville"})
    cov = opendata.coverage("x")
    assert cov["kinds"] == {"crash": ["x-crashes"]} and "office" in cov["missing"] and "crash" not in cov["missing"]


def test_an_abbreviated_corner_is_found_by_its_written_out_name(monkeypatch):
    monkeypatch.setattr(brief, "gazetteer", lambda: {})
    tried = []

    def lookup(address):
        tried.append(address)
        if address != "3rd Avenue & Pine Street, Seattle, WA":
            raise ValueError(f"no intersection: {address}")
        return 47.61, -122.34, address
    monkeypatch.setattr(brief, "_lookup", lookup)
    assert brief.geocode("3rd Ave & Pine St, Seattle, WA")[:2] == (47.61, -122.34)
    assert tried[0] == "3rd Ave & Pine St, Seattle, WA"
    monkeypatch.setattr(brief, "_lookup", lambda a: (_ for _ in ()).throw(ValueError(f"no intersection: {a}")))
    with pytest.raises(ValueError, match="no intersection: Main St & 1st Ave, Portland"):
        brief.geocode("Main St & 1st Ave, Portland")


def test_a_place_outside_every_city_is_refused_before_the_intersection_search(monkeypatch):
    calls = []

    def fetch(url, params=None, **k):
        calls.append(url)
        return [{"lat": "45.5", "lon": "-122.6", "display_name": "Portland"}], None
    monkeypatch.setattr(brief.context, "fetch", fetch)
    monkeypatch.setattr(brief, "gazetteer", lambda: {})
    with pytest.raises(brief.OutsideCoverage, match="outside the cities this copy covers"):
        brief.geocode("Main St & 1st Ave, Portland, OR")
    assert len(calls) == 1  # one place search, no Overpass, no other spellings


def test_an_unknown_category_is_never_a_pattern():
    from nearmisslens import rootcause
    a = {"crash_type_fields": ["type"], "factor_fields": ["f"], "labels": {"9": "Bicycle-Unknown/Not Stated"}}
    tags, _ = rootcause.tags({"type": "Bicycle-Unknown/Not Stated", "f": "Speeding"}, a)
    assert "crash type: bicycle-unknown/not stated" not in tags and "factor: speeding" in tags
    tags, _ = rootcause.tags({"type": "9", "f": "Not Reported"}, a)
    assert not any("unknown" in t or "not reported" in t for t in tags)
    tags, _ = rootcause.tags({"type": "Broadside", "f": ""}, a)
    assert "crash type: broadside" in tags


def test_a_long_street_is_found_inside_the_named_city_and_with_a_direction_word(monkeypatch, tmp_path):
    """'Milwaukee Avenue, Chicago' first matched a suburb on the same road, and 'Division Street' a small street of
    that name across town: the search is repeated inside the city's box, and the crossing found with OSM's names
    ('North Milwaukee Avenue', 'West Division Street')."""
    asked = []

    def fetch(url, params=None, data=None, **k):
        if data:
            asked.append(data["data"])
            hit = "North|South" in data["data"] and "41.64,-87.94,42.03,-87.52" in data["data"]
            return {"elements": [{"type": "node", "lat": 41.9034, "lon": -87.6665}] if hit else []}, None
        if params["q"].startswith("Milwaukee"):
            return ([{"lat": "41.8926", "lon": "-87.6498", "display_name": "N Milwaukee Ave, Chicago"}]
                    if params.get("bounded") else [{"lat": "42.10", "lon": "-87.88", "display_name": "Wheeling"}]), None
        return [{"lat": "41.6735", "lon": "-87.67"}], None  # another Division Street, far south
    monkeypatch.setattr(brief.context, "fetch", fetch)
    monkeypatch.setattr(brief, "GEOCODES", tmp_path / "geocodes.json")
    monkeypatch.setattr(brief, "gazetteer", lambda: {})
    lat, lon, name = brief._lookup("Milwaukee Avenue & Division Street, Chicago")
    assert (lat, lon) == (41.9034, -87.6665) and len(asked) == 2  # the exact names first (cached runs), then the city


def test_no_city_comparison_is_said_plainly(monkeypatch):
    """A city with no screened priority junctions (Chicago here) has nothing to compare against: the report says so,
    instead of "no pattern stands out against the city's priority junctions"."""
    from nearmisslens import engineer
    monkeypatch.setattr(engineer.rootcause, "analyse", lambda lat, lon, **k: {
        "crashes": 66, "baseline": None, "enough_crashes": True, "over_represented": [], "source": "x"})
    desk = engineer.Desk()
    data, rid = engineer.root_cause(desk, 41.9, -87.66)
    summary = next(r["summary"] for r in desk.receipts if r["id"] == rid)
    assert "not compared" in summary and "stands out" not in summary
    src = inspect.getsource(engineer.claims_for)
    assert "is not compared with the rest of the city" in src  # the report's sentence for the same case


def test_letters_say_only_what_is_checked():
    """Independent test: 'Dear colleagues at route designation only; confirm ownership', a 'state DOT' in a district
    that has none, a project dated 2032 described as done, and a site condition stated as a fact."""
    from nearmisslens import jurisdiction, letter, opendata
    assert letter._salutation([{"party": "the District Department of Transportation (DDOT) (route designation only; "
                                         "confirm ownership)"}]) == "Dear colleagues at DDOT,"
    dc = opendata.city("dc")
    rows = jurisdiction.osm_designations({"roads": [{"name": "Rhode Island Avenue NE", "ref": ["US 1"]}]}, dc)
    assert rows and "state transportation department" not in rows[0]["party"] and "DDOT" in rows[0]["party"]
    facts = {"fixes": [{"needs_site_check_for": "an entry on yellow or red; the current yellow plus all-red is shorter "
                                                "than ITE practice"}]}
    bad = "The current yellow plus all-red here is shorter than ITE practice."
    good = "Please check on site whether the current yellow plus all-red is shorter than ITE practice."
    assert letter.condition_errors(bad, facts) and not letter.condition_errors(good, facts)
    # independent test round 2: the hedge of one clause does not cover the next one
    joined = "This needs a site check for an entry on yellow or red; the current yellow plus all-red is shorter than ITE practice."
    assert letter.condition_errors(joined, facts)


def test_a_town_inside_a_citys_box_is_not_the_city(monkeypatch):
    """A suburb inside the bounding box (River Forest in Chicago's) would be investigated against the city's crash
    records, which do not cover it, and show no crashes. An address that names such a town is refused; a long street
    whose first match is in a suburb is not (the address names the city)."""
    from nearmisslens import opendata
    chi = opendata.city("chicago")
    assert not brief.in_city_limits("Lake Street, River Forest, Proviso Township, Cook County, Illinois, 60305, United States", chi)
    assert brief.in_city_limits("Division Street, West Town, Chicago, Cook County, Illinois, 60622, United States", chi)
    assert not brief.in_city_limits("Main Street, Yonkers, Westchester County, New York, 10701, United States", opendata.city("nyc"))

    def fetch(url, params=None, data=None, **k):
        if data:
            return {"elements": []}, None
        if "River Forest" in params["q"]:
            return [{"lat": "41.888", "lon": "-87.814", "display_name": "Lake Street, River Forest, Proviso Township, "
                                                                       "Cook County, Illinois, 60305, United States"}], None
        return [{"lat": "41.70", "lon": "-87.66", "display_name": "Ashland Avenue, Calumet Park, Cook County, Illinois, "
                                                                   "60827, United States"}], None
    monkeypatch.setattr(brief.context, "fetch", fetch)
    with pytest.raises(brief.OutsideCoverage, match="River Forest"):
        brief._lookup("Lake Street & Franklin Avenue, River Forest")
    with pytest.raises(ValueError) as e:  # a city street whose first match is in a suburb goes on to the crossing search
        brief._lookup("Ashland Avenue & Cullerton Street, Chicago")
    assert not isinstance(e.value, brief.OutsideCoverage)


def test_one_addressee_per_agency():
    from nearmisslens import letter
    who = {"owners": [{"party": "the District Department of Transportation (DDOT)", "roads": ["A St"], "confidence": "inferred"},
                      {"party": "the District Department of Transportation (DDOT) (route designation only; confirm ownership)",
                       "roads": ["B Ave"], "confidence": "designation only"}], "requesters": []}
    brief = {"junction": "A St & B Ave", "dossier": {"lat": 0, "lon": 0, "crashes": {}, "plans": {}, "city": "dc", "years": 5}, "fixes": {}}
    f = letter.facts(brief, offices_=[], who=who, audience="agency")
    assert f["to"] == "the District Department of Transportation (DDOT)" and f["road_owners"][0]["roads"] == ["A St", "B Ave"]


def test_a_letter_counts_the_deaths_a_city_records_without_their_mode():
    """Independent audit: letters said 'no one was killed' at corners where the record has deaths, because a city
    that records deaths without the mode (any_killed) was summed by mode only."""
    from nearmisslens import context, harm, letter
    cr = {"injury_crashes": 30, "crashes": 60, "any_killed": 4, "since": "2021-10-31"}
    assert context.deaths(cr) == 4 and context.deaths({"pedestrian_killed": 1, "cyclist_killed": 1}) == 2
    assert harm.junction(cr, 5)["deaths_in_record"] == 4
    brief = {"junction": "A St & B Ave", "dossier": {"lat": 0, "lon": 0, "crashes": cr, "plans": {}, "city": "seattle",
                                                     "years": 5}, "fixes": {}}
    assert letter.facts(brief, offices_=[])["people_killed"] == 4


def test_lighting_is_not_estimated_where_the_record_says_the_lights_were_on():
    """Independent audit: lighting was valued at corners where the record codes 80-94% of after-dark crashes as with
    street lights on; its estimate is for an unlit corner."""
    from nearmisslens import brief, countermeasures
    base = {"crashes": {"injury_crashes": 60, "crashes": 120, "dark_share": 0.4, "dark_crashes": 48, "since": "2021-10-31",
                        "crash_groups": {}, "recorded": {"injured_by_mode": [], "killed": False}},
            "street": {"signals": 2, "roads": [{"name": "A"}]}, "plans": {"projects": []}, "city": "zz", "years": 5}
    lit = brief.fix_options({**base, "crashes": {**base["crashes"], "dark_lit_share": 0.9}}, countermeasures.load_cmf())
    unlit = brief.fix_options({**base, "crashes": {**base["crashes"], "dark_lit_share": 0.2}}, countermeasures.load_cmf())
    names = lambda fx: {o["countermeasure"] for o in fx["options"]}
    assert "Lighting" in names(unlit) and "Lighting" not in names(lit)
    assert any("street lights on" in (o.get("reason") or "") for o in lit["not_estimated"] if o["countermeasure"] == "Lighting")
