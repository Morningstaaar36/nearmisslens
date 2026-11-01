from nearmisslens import jurisdiction as J

ADAPTER = {"id": "inv", "kind": "jurisdiction", "endpoint": "https://x/0", "name_field": "Name",
           "route_fields": ["Sign", "Num"], "owner_field": "Owner", "region_field": "Region", "radius_m": 30,
           "covers": "state routes only", "owners": {"01-STATE": "the state DOT, Region {region}", "04-City": "city"},
           "source": "Test inventory"}
CITY = {"id": "c", "name": "Test City", "agency": "the Test City DOT"}


def _setup(monkeypatch, features):
    monkeypatch.setattr(J.context, "city_of", lambda lat, lon: "c")
    monkeypatch.setattr(J.opendata, "city", lambda c: CITY)
    monkeypatch.setattr(J.opendata, "adapters_for", lambda lat, lon, kind: [ADAPTER] if kind == "jurisdiction" else [])
    monkeypatch.setattr(J.opendata, "offices_at", lambda lat, lon: [])
    monkeypatch.setattr(J.context, "fetch", lambda url, params=None, **k: ({"features": [{"attributes": f} for f in features]}, 0))


def test_owners_come_from_the_inventory_and_unlisted_streets_are_inferred_city_streets(monkeypatch):
    _setup(monkeypatch, [{"Name": "Main Expressway", "Sign": "I", "Num": "95", "Owner": "01-STATE", "Region": "11"},
                         {"Name": None, "Sign": "I", "Num": "95", "Owner": "01-STATE", "Region": "11"}])
    out = J.who_must_act(0, 0, ["Main Expressway", "Oak Street"])
    state = next(r for r in out["owners"] if r["confidence"] == "recorded")
    assert state["party"] == "the state DOT, Region 11" and state["roads"] == ["Main Expressway (I 95)"]
    city = next(r for r in out["owners"] if r["confidence"] == "inferred")
    assert city["party"] == "the Test City DOT" and city["roads"] == ["Oak Street"]
    assert all(r["basis"]["dataset"] for r in out["owners"])


def test_without_an_inventory_osm_route_tags_are_designation_only(monkeypatch):
    monkeypatch.setattr(J.context, "city_of", lambda lat, lon: "c")
    monkeypatch.setattr(J.opendata, "city", lambda c: CITY)
    monkeypatch.setattr(J.opendata, "adapters_for", lambda lat, lon, kind: [])
    monkeypatch.setattr(J.opendata, "offices_at", lambda lat, lon: [])
    layout = {"roads": [{"name": "Route Road", "ref": ["US 1"]}, {"name": "Elm Street", "ref": []}]}
    out = J.who_must_act(0, 0, ["Route Road", "Elm Street"], layout)
    conf = {r["roads"][0]: r["confidence"] for r in out["owners"]}
    assert conf == {"Route Road": "designation only", "Elm Street": "inferred"}


def test_one_entry_per_agency_with_inferred_roads_named():
    rows = [{"party": "city", "roads": ["Main Ave (NY 1)"], "confidence": "recorded", "basis": {"dataset": "inv"}, "route": "NY 1"},
            {"party": "city", "roads": ["Oak St"], "confidence": "inferred", "basis": {"dataset": "inv"}, "route": None},
            {"party": "state", "roads": ["I 95"], "confidence": "recorded", "basis": {"dataset": "inv"}, "route": "I 95"}]
    out = J.merge_parties(rows)
    assert [o["party"] for o in out] == ["city", "state"]
    assert out[0]["confidence"] == "recorded" and out[0]["roads"] == ["Main Ave (NY 1)", "Oak St"]
    assert out[0]["inferred_roads"] == ["Oak St"] and "inferred_roads" not in out[1]


def test_city_without_owner_data_or_street_layout_presumes_its_agency(monkeypatch):
    from nearmisslens import jurisdiction as J, opendata, context, engineer
    monkeypatch.setattr(context, "city_of", lambda lat, lon: "dc")
    monkeypatch.setattr(J, "owners", lambda lat, lon, streets: {"owners": [], "adapter": False})
    monkeypatch.setattr(opendata, "offices_at", lambda lat, lon: [])
    w = J.who_must_act(38.9, -77.0, ["North Capitol Street", "Michigan Avenue"], {"roads": []})
    assert len(w["owners"]) == 1 and "DDOT" in w["owners"][0]["party"]
    assert w["owners"][0]["roads"] == ["North Capitol Street", "Michigan Avenue"]
    assert engineer._basis(w["owners"][0]) == "no road-owner dataset registered for this city, so presumed a city street"
