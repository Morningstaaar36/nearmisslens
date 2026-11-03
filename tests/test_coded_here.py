"""Independent test round 3: a 100 m circle can hold more of the neighbouring corners' crashes than this corner's own
(Cesar Chavez & Florida: 3 of 23 coded there, 14 at Alabama, 6 at Bryant). Where the dataset codes each crash's
streets, the report says so and a review cannot say "proceed" without counting this corner's own (no network)."""
from nearmisslens import brief, review

CR = {"street_coded": 23, "street_pairs": [
    {"pair": "Alabama St & Cesar Chavez St", "crashes": 14, "injury_crashes": 14},
    {"pair": "Bryant St & Cesar Chavez St", "crashes": 6, "injury_crashes": 6},
    {"pair": "Cesar Chavez St & Florida St", "crashes": 3, "injury_crashes": 3}]}


def test_the_crashes_coded_at_the_corner_are_counted_and_the_rest_named():
    ch = brief.coded_here(CR, "Florida Street & Cesar Chavez Street, San Francisco")
    assert (ch["at_corner"], ch["coded"], ch["mostly_elsewhere"]) == (3, 23, True)
    s = brief.coded_sentence("Florida Street & Cesar Chavez Street, San Francisco", ch)
    assert "codes 3 of the 23" in s and "Alabama St & Cesar Chavez St 14" in s
    assert not brief.coded_here(CR, "Alabama Street & Cesar Chavez Street")["mostly_elsewhere"]
    assert brief.coded_here({"street_coded": 2, "street_pairs": []}, "A St & B Ave") is None  # too few to say


def test_ordinals_match_a_dataset_that_writes_none():
    assert brief.same_corner("East 169 Street & Teller Avenue", "East 169th Street & Teller Ave")
    assert brief.same_corner("04Th St & Channel St", "4th Street & Channel Street")  # San Francisco pads numbers
    assert not brief.same_corner("14th St & Channel St", "4th Street & Channel Street")


def test_a_review_cannot_proceed_on_other_corners_crashes():
    from tests.test_review import FX
    part = [{"countermeasure": "Leading Pedestrian Interval", "what": "LPI"}]
    plain = review.appraise_proposal(FX, part, 15000.0, "this fix only")
    ch = brief.coded_here(CR, "Florida Street & Cesar Chavez Street")
    flagged = review.appraise_proposal(FX, part, 15000.0, "this fix only", coded=ch)
    if plain["verdict"] in ("proceed", "compare_alternative"):
        assert flagged["verdict"] == "proceed_after_site_check"
    assert "codes 3 of the 23" in flagged["parts"][0]["reasons"][0] and flagged["coded_at_corner"] == ch


def test_every_location_coding_places_a_crash():
    from nearmisslens import opendata as O
    pair = {"street_fields": ["on", "cross"]}
    assert O.crash_place({"on": "MISSION ST", "cross": "16TH ST"}, pair) == ("pair", "Mission St", "16Th St")
    assert O.crash_place({"on": "BROADWAY", "cross": ""}, pair) == ("segment", "Broadway")  # no cross street: mid-block
    text = {"location": {"text_field": "LOC", "between": " BETWEEN ", "and": " AND "}}
    assert O.crash_place({"LOC": "RAINIER AVE S AND S GENESEE ST"}, text) == ("pair", "Rainier Ave S", "S Genesee St")
    assert O.crash_place({"LOC": "RAINIER AVE S BETWEEN S OREGON ST AND S ALASKA ST"}, text) == ("segment", "Rainier Ave S")
    mid = {"location": {"text_field": "LOC", "and": " AND ", "midblock": {"field": "J", "pattern": "^Mid-Block \\(not"}}}
    assert O.crash_place({"LOC": "A ST AND B ST", "J": "Mid-Block (not related to intersection)"}, mid) == ("segment",)
    assert O.crash_place({"LOC": "A ST AND B ST", "J": "At Intersection"}, mid) == ("pair", "A St", "B St")
    off = {"location": {"address_field": "ADDRESS", "max_offset": {"field": "OFF", "metres": 30}}}
    assert O.crash_place({"ADDRESS": "10 A ST", "OFF": "45.2"}, off) == ("segment",)
    assert O.crash_place({"ADDRESS": "10 A ST", "OFF": "7.5"}, off) == ("street", "A St")
    addr = {"location": {"address_field": "ADDRESS", "cross_field": "NEAR"}}
    assert O.crash_place({"ADDRESS": "1120 22ND STREET NW", "NEAR": "M ST NW"}, addr) == ("pair", "22Nd Street Nw", "M St Nw")
    assert O.crash_place({"street_name": "ASHLAND AVE"}, {"location": {"street_field": "street_name"}}) == ("street", "Ashland Ave")
    assert O.crash_place({}, {}) is None


def test_a_crash_is_the_corners_unless_placed_elsewhere():
    from nearmisslens import opendata as O
    corner = "22nd Street Northwest & L Street Northwest"
    assert O.at_corner(("pair", "22Nd Street Nw", "L St Nw"), corner) is True
    assert O.at_corner(("pair", "22Nd Street Nw", "M St Nw"), corner) is False  # the next corner up
    assert O.at_corner(("street", "22Nd Street Nw"), corner) is True  # on one of its streets, not placed elsewhere
    assert O.at_corner(("street", "K St Nw"), corner) is False
    assert O.at_corner(None, corner) is None  # the dataset does not say: kept
    assert O.at_corner(("segment", "22Nd Street Nw"), corner) is False  # placed mid-block by the dataset


def test_the_summary_keeps_the_corners_own_crashes_and_says_what_it_left_out(monkeypatch):
    from nearmisslens import opendata as O
    a = {"id": "zz-crashes", "source": "zz", "date_field": "d", "injured": {"any": ["n"]}, "killed": {"any": ["k"]},
         "street_fields": ["on", "cross"]}
    rows = [{"d": "2026-01-01", "n": "1", "k": "0", "on": x, "cross": y} for x, y in
            [("CESAR CHAVEZ ST", "FLORIDA ST")] * 3 + [("CESAR CHAVEZ ST", "ALABAMA ST")] * 14 + [("", "")] * 2]
    monkeypatch.setattr(O, "rows_near", lambda *a, **k: rows)
    s = O.crash_summary(a, 0, 0, corner="Florida Street & Cesar Chavez Street")
    assert s["injury_crashes"] == 5 and s["attribution"] == {"by": "where the dataset places each crash",
                                                             "within_radius": 19, "kept": 5, "left_out_elsewhere": 14,
                                                             "not_placed": 2}
    assert O.crash_summary(a, 0, 0)["injury_crashes"] == 19  # without a corner name: the circle, as before


def test_a_street_is_found_however_its_name_is_written():
    """T29: "SW Hinds St" was searched as "Hinds Street Southwest"; the map names it "Southwest Hinds Street"."""
    import re
    p = brief.street_pattern
    for written, mapped in [("SW Hinds St", "Southwest Hinds Street"), ("SW Hinds St", "Hinds Street Southwest"),
                            ("Seward Park Ave S", "Seward Park Avenue South"), ("E 169th St", "East 169 Street"),
                            ("Rev James A Polite Ave", "Reverend James A. Polite Avenue")]:
        assert re.fullmatch(p(written), mapped, re.I), (written, mapped)
    assert not re.fullmatch(p("9th Ave"), "19th Avenue", re.I)
    assert not re.fullmatch(p("SW Hinds St"), "Southwest Hinds Way", re.I)


def test_initials_jr_and_roadway_tags_match_the_full_name():
    """T31b: Seattle's record writes "M L King Jr Wr Way S" (WR: the west roadway) for Martin Luther King Jr Way S."""
    full = "Martin Luther King Junior Way South & South Othello Street"
    assert brief.same_corner("M L King Jr Wr Way S & S Othello St", full)
    assert brief.same_corner(full, "M L King Jr Er Way S & S Othello St")
    assert not brief.same_corner("Lake St & Franklin Ave", "Lake St & Frank Ave")
