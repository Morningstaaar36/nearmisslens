"""A source's sentence is 'consistent with the record' only when a number in it was tested against the record (the
T21d review found times, grants and one crash's victims passed as consistent or differing)."""
import pytest

from nearmisslens import orchestrator as O

DATA = {"crashes": {"injury_crashes": 56, "pedestrians_injured": 4, "cyclists_injured": 1, "any_killed": 1,
                    "harm_usd_per_year": 342400}}


@pytest.fixture
def verdict():
    places = O._places(O.Desk("dc"))
    return lambda t: O.claim_verdict(t, DATA, places, None)[0]


@pytest.mark.parametrize("text, want", [
    ("56 injury crashes were reported near the corner.", "consistent with the record"),
    ("60 injury crashes were reported near the corner.", "differs from the record"),
    ("One person was killed in crashes near the corner.", "consistent with the record"),
    ("Three people were killed in crashes near the corner.", "differs from the record"),
    ("At about 12:17 a.m., officers received reports of a collision.", "cannot be checked against this record"),
    ("The senator secured $1.2 million in state funds for bike lanes.", "cannot be checked against this record"),
    ("There are 116 intersections where five or more people were killed.", "cannot be checked against this record"),
    ("Two women are dead after they were struck by a car.", "cannot be checked against this record"),
    ("Officers responded to the crash.", "cannot be checked against this record"),
])
def test_a_verdict_rests_on_a_tested_number(verdict, text, want):
    assert verdict(text) == want


def test_number_words_are_counts():
    assert O.words_to_digits("Two women are dead") == "2 women are dead"
    assert O.words_to_digits("one of the worst corners") == "one of the worst corners"


def test_a_count_label_never_lists_a_cost():
    from nearmisslens import context
    errs = context.FactCheck(DATA).text("60 injury crashes were reported.")
    assert errs and "342400" not in errs[0]


@pytest.mark.parametrize("text, want", [
    ("There have been at least 50 injury crashes near the corner.", "consistent with the record"),
    ("There have been at least 90 injury crashes near the corner.", "differs from the record"),
    ("There have been fewer than 60 injury crashes near the corner.", "consistent with the record"),
])
def test_a_bound_holds_where_the_record_count_meets_it(verdict, text, want):
    assert verdict(text) == want


@pytest.mark.parametrize("text, want", [
    ("The corner had 9 KSI in 5 crashes.", "cannot be checked against this record"),
    ("Police rebooked the driver following the October 19 death of the victim.", "cannot be checked against this record"),
    ("At the U.S. DOT's values that harm costs about $342,400 a year.", "consistent with the record"),
    ("Crashes here cut by 27 percent.", "cannot be checked against this record"),
])
def test_severity_dates_costs_and_percent_words(verdict, text, want):
    assert verdict(text) == want


def test_a_replayed_case_reads_the_window_it_ran_in():
    case = {"final": {"findings": [{"text": "A & B had 5 injury crashes since 2021-11-02."}]}}
    assert O.run_asof(case) == "2026-11-02"
    assert O.run_asof({"asof": "2026-10-31"}) == "2026-10-31"


def test_another_period_or_area_is_not_the_record():
    data = {"crashes": {**DATA["crashes"], "since": "2021-11-02"}}
    places = O._places(O.Desk("dc"))
    v = lambda t: O.claim_verdict(t, data, places, None)[0]
    assert v("From 2015 to 2020 there were 90 injury crashes here.") == "cannot be checked against this record"
    assert v("The corridor had 90 injury crashes.") == "cannot be checked against this record"
    assert v("Since 2021 there were 90 injury crashes here.") == "differs from the record"


def test_a_redacted_quote_still_matches_its_page(monkeypatch):
    page = "The blue sedan with license plate 9ABC123 is blocking the driveway at the corner every morning."
    monkeypatch.setattr(O, "text_of", lambda url, known=None: page)
    quote = O.redact("license plate 9ABC123 is blocking the driveway")
    assert "9ABC123" not in quote and O.quote_check(quote, "https://x") == "verified"
