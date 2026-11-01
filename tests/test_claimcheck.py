from nearmisslens import claimcheck as C

R = {"crashes": {"injury_crashes": 129, "pedestrian_injured": 29},
     "programs": [{"label": "turn traffic calming", "sites": 227, "theta": 0.839}],
     "options": [{"harm_avoided_usd_per_year": 1325000.0}]}


def test_code_checks_each_assertion_the_model_reads_out():
    ok = {"assertions": [{"quote": "29 pedestrians were injured", "field": "crashes.pedestrian_injured", "value": 29,
                          "kind": "count"}], "causal_or_certain": False, "untied": []}
    assert C.verify("Here 29 pedestrians were injured.", R, ok) == []
    killed = {**ok, "assertions": [{**ok["assertions"][0], "quote": "29 pedestrians were killed",
                                    "field": "crashes.pedestrian_killed"}]}
    assert C.verify("Here 29 pedestrians were killed.", R, killed)          # absent deaths field: zero, not 29
    none = {"assertions": [{"quote": "no pedestrians were injured", "field": "crashes.pedestrian_injured", "value": None,
                            "kind": "none"}], "causal_or_certain": False, "untied": []}
    assert C.verify("Here no pedestrians were injured.", R, none)


def test_quotes_must_be_in_the_claim_and_numbers_must_be_tied():
    fake = {"assertions": [{"quote": "something else", "field": "crashes.injury_crashes", "value": 129, "kind": "count"}],
            "causal_or_certain": False, "untied": []}
    assert C.verify("There were 129 injury crashes.", R, fake)
    assert C.verify("There were 129 injury crashes.", R, {"assertions": [], "causal_or_certain": False, "untied": ["129"]})


def test_scalings_for_shares_changes_and_money():
    a = lambda q, f, v, k: {"assertions": [{"quote": q, "field": f, "value": v, "kind": k}], "causal_or_certain": False,
                            "untied": []}
    assert C.verify("Turn calming fell 16%.", R, a("fell 16%", "programs.0.theta", 16, "change")) == []
    assert C.verify("worth $1.3 million", R, a("$1.3 million", "options.0.harm_avoided_usd_per_year", 1.3, "money")) == []
    assert C.verify("Turn calming was tested at 1,651 sites.", R, a("1,651 sites", "programs.0.sites", 1651, "count"))


def test_dates_rounded_percentages_and_frame_numbers():
    rec = {"crashes": {"since": "2021-10-31", "crashes": 172}, "patterns": [{"city_share": 0.062}]}
    a = lambda q, f, v, k: {"assertions": [{"quote": q, "field": f, "value": v, "kind": k}], "causal_or_certain": False,
                            "untied": ["five", "95%"]}
    assert C.verify("172 crashes since October 31, 2021, in the five-year window", rec,
                    a("since October 31, 2021", "crashes.since", 2021, "year")) == []
    assert C.verify("about 6% at priority junctions", rec, a("6% at priority junctions", "patterns.0.city_share", 6, "share")) == []
    assert C.verify("about 8% at priority junctions", rec, a("8% at priority junctions", "patterns.0.city_share", 8, "share"))
