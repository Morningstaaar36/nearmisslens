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
    two = a("since October 31, 2021", "crashes.since", 2021, "year")
    two["assertions"].append({"quote": "172 crashes", "field": "crashes.crashes", "value": 172, "kind": "count"})
    assert C.verify("172 crashes since October 31, 2021, in the five-year window", rec, two) == []
    assert C.verify("172 crashes since October 31, 2021, in the five-year window", rec,
                    a("since October 31, 2021", "crashes.since", 2021, "year"))  # 172 left out of every assertion
    assert C.verify("about 6% at priority junctions", rec, a("6% at priority junctions", "patterns.0.city_share", 6, "share")) == []
    assert C.verify("about 8% at priority junctions", rec, a("8% at priority junctions", "patterns.0.city_share", 8, "share"))


def test_the_model_read_check_is_a_second_gate_on_agent_claims():
    import json
    from nearmisslens import engineer
    class Fake:
        def cached(self, ns, req, run, cost, est, what, require_text=False, complete=None):
            return run()
        def create_response(self, payload):
            out = {"assertions": [{"quote": "29 pedestrians were killed", "field": "crashes.pedestrian_killed",
                                   "value": 29, "kind": "count"}], "causal_or_certain": False, "untied": []}
            return {"status": "completed", "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(out)}]}]}
    errs = engineer.model_read_errors("Here 29 pedestrians were killed.", R, Fake())
    assert errs and errs[0].startswith("model-read check")
    assert engineer.model_read_errors("anything", R, None) == []


def test_no_complement_shares_no_slack_on_counts_and_none_needs_a_real_parent():
    rec = {"crashes": {"crashes": 310, "pedestrian_injured": 29}, "patterns": [{"share": 0.277}]}
    a = lambda q, f, v, k: {"assertions": [{"quote": q, "field": f, "value": v, "kind": k}], "causal_or_certain": False,
                            "untied": []}
    assert C.verify("72% of crashes involved a truck", rec, a("72% of crashes", "patterns.0.share", 72, "share"))
    assert not C.verify("28% of crashes involved a truck", rec, a("28% of crashes", "patterns.0.share", 28, "share"))
    assert C.verify("313 crashes", rec, a("313 crashes", "crashes.crashes", 313, "count"))
    assert C.verify("no one died", rec, a("no one died", "made.up.deaths", None, "none"))
