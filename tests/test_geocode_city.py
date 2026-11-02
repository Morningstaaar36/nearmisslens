"""The offline geocode table answers only in the city the address names (verifier1 A2)."""
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
    calls = iter([([{"lat": "40.7", "lon": "-74.0", "display_name": "x"}], None),
                  ([{"lat": "40.7", "lon": "-74.0"}], None),
                  ({"elements": [{"type": "node", "lat": 40.71, "lon": -74.0}]}, None)])
    monkeypatch.setattr(brief.context, "fetch", lambda *a, **k: next(calls))
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
