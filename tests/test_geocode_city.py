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
