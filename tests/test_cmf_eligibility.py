from nearmisslens import brief
from nearmisslens import countermeasures as cm


def _dossier(signals=1, stops=0, wet=None, dark=None, typed=False):
    cr = {"crashes": 300, "injury_crashes": 120, "crash_type_recorded": typed, "adapter": "nyc-crashes",
          "crash_groups": {"pedestrian": 30, "rear_end": 20, "angle_turning": 40},
          "factor_counts": {"Failure to Yield Right-of-Way": 60, "Traffic Control Disregarded": 40},
          "wet_share": wet, "dark_share": dark}
    return {"city": "nyc", "crashes": cr, "plans": {"projects": []},
            "street": {"signals": signals, "stop_signs": stops, "roads": [{"name": "A"}]}}


def test_bad_records_are_never_used_at_any_site():
    db = cm.load_cmf()
    for kw in ({"signals": 1}, {"signals": 0, "stops": 2}, {"signals": 0, "stops": 0}):
        for typed in (False, True):
            o = brief.fix_options(_dossier(wet=0.3, dark=0.4, typed=typed, **kw), db)
            used = {x["cmf_id"] for x in o["options"]}
            assert not used & {"9743", "12138", "1447", "9739", "9735"}
            if kw.get("signals"):
                assert "8799" not in used and "10608" not in used


def test_refuge_islands_are_estimated_only_at_uncontrolled_crossings():
    db = cm.load_cmf()
    sig = brief.fix_options(_dossier(signals=1), db)
    unc = brief.fix_options(_dossier(signals=0, stops=0), db)
    name = "Medians and Pedestrian Refuge Islands in Urban and Suburban Areas"
    assert name in {x["countermeasure"] for x in sig["not_estimated"]}
    assert next(x for x in unc["options"] if x["countermeasure"] == name)["cmf_id"] == "8799"


def test_wet_and_dark_records_need_the_recorded_share():
    db = cm.load_cmf()
    none = brief.fix_options(_dossier(), db)
    skipped = {x["countermeasure"]: x["reason"] for x in none["not_estimated"]}
    assert "darkness" in skipped["Lighting"] and "wet roads" in skipped["Pavement Friction Management"]
    with_shares = brief.fix_options(_dossier(wet=0.25, dark=0.5), db)
    light = next(x for x in with_shares["options"] if x["countermeasure"] == "Lighting")
    assert light["target_crashes_5y"] == 60.0  # 120 injury crashes x 0.5 in darkness


def test_pick_is_the_cited_record_or_the_median_never_the_largest_effect():
    db = cm.load_cmf()
    o = {x["countermeasure"]: x for x in brief.fix_options(_dossier(), db)["options"]}
    assert o["Leading Pedestrian Interval"]["cmf_id"] == "9918"          # cited, not 9903 (0.81)
    assert o["Yellow Change Intervals"]["cmf_id"] == "4215"              # median of 4, not 4216 (0.662)
    assert o["Yellow Change Intervals"]["cmf_range"] == [0.662, 0.937]


def test_reconstructions_rank_after_low_cost_fixes():
    o = brief.fix_options(_dossier(), cm.load_cmf())["options"]
    scales = [x["scale"] for x in o]
    assert scales == sorted(scales, key=lambda s: s == "reconstruction")


def test_shipped_subset_has_every_curated_record():
    sub = cm._load(str(cm.ALLOWED_PATH))
    ids = {e["crfid"] for i in cm.psc_items() for e in i.get("cmf_allow", [])}
    assert ids <= set(sub["crfid"])


def test_number_checker_binds_numbers_to_their_labels():
    from nearmisslens.context import FactCheck
    facts = {"crashes": {"crashes": 310, "injury_crashes": 129, "pedestrian_injured": 29, "motorist_injured": 160,
                         "by_year": {"2021": 12}},
             "fixes": {"options": [{"expected_crashes_avoided_per_year": 7.0, "harm_avoided_usd_per_year": 2403000.0}],
                       "harm": {"usd_per_year": 8834000.0}}}
    c = FactCheck(facts)
    assert c.text("29 pedestrians were killed in 2021.")
    assert c.text("There were 310 deaths and 129 crashes.")
    assert c.text("Refuge islands would prevent 29 pedestrian injury crashes a year.")
    assert c.text("129 pedestrians were injured.")
    assert c.text("29 pedestrians were injured and 129 injury crashes were recorded.") == []
    assert c.text("Longer yellow times would prevent about 7.0 injury crashes a year, worth $2,403,000.") == []
    assert c.text("The harm costs about $8.8 million a year; no one was killed (0 deaths).") == []


def test_school_crosswalk_record_is_used_only_at_school_crossings():
    db = cm.load_cmf()
    plain = brief.fix_options(_dossier(), db)
    skipped = {x["countermeasure"]: x["reason"] for x in plain["not_estimated"]}
    assert "school crossings" in skipped["Crosswalk Visibility Enhancements"]
    assert "2697" not in {x["cmf_id"] for x in plain["options"]}
    school = brief.fix_options({**_dossier(), "site_kinds": ["school crossings"]}, db)
    assert "2697" in {x["cmf_id"] for x in school["options"]}


def test_a_precondition_the_data_cannot_show_puts_the_fix_behind_a_site_check():
    o = {x["countermeasure"]: x for x in brief.fix_options(_dossier(), cm.load_cmf())["options"]}
    y = o["Yellow Change Intervals"]
    assert y["evidence"] == "needs a site check" and "ITE" in y["verify_on_site"]


def test_a_fix_the_city_measured_ranks_first_and_says_so():
    o = brief.fix_options(_dossier(), cm.load_cmf())["options"]
    lpi = next(x for x in o if x["countermeasure"] == "Leading Pedestrian Interval")
    assert lpi["evidence"] == "measured here" and lpi["local_evidence"]["sites"] > 1000
    low = [x for x in o if x["scale"] == "low-cost"]
    assert low[0]["countermeasure"] == "Leading Pedestrian Interval"
    tiers = [brief.EVIDENCE.index(x["evidence"]) for x in low]
    assert tiers == sorted(tiers)
