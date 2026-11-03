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
