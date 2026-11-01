from nearmisslens import redteam as T

FX = {"crashes": {"injury_crashes": 129, "pedestrian_injured": 29, "cyclist_injured": 3, "crashes": 310},
      "options": [{"countermeasure": "Backplates with Retroreflective Borders", "cmf": 0.85, "cmf_id": "1410",
                   "expected_crashes_avoided_per_year": 3.9, "evidence": "FHWA-cited"}]}
CASE = {"junction": {"name": "Bruckner Boulevard & Hunts Point Avenue, New York City"},
        "receipts": [{"id": "R3", "tool": "choose_fixes"}], "findings": {"choose_fixes": FX}}


def test_paths_reach_nested_fields():
    assert T.get_path(FX, "crashes.pedestrian_injured") == 29
    assert T.get_path(FX, "options.0.cmf") == FX["options"][0]["cmf"]
    assert T.get_path(FX, "crashes.nope") is None


def test_a_false_claim_counts_only_when_its_spec_checks_out_against_the_receipt():
    ok = {"error_type": "wrong_label", "claim": "29 people were killed here.", "field": "crashes.injury_crashes",
          "record_value": 129, "claimed_value": 29}
    assert T.verify_false(FX, ok)
    lie_about_record = {**ok, "record_value": 30}           # the attacker misquotes the record: dropped
    assert T.verify_false(FX, lie_about_record) is None
    not_false = {**ok, "claim": "129 injury crashes.", "claimed_value": 129}
    assert T.verify_false(FX, not_false) is None
    absent = {"error_type": "false_absence", "claim": "No cyclist was hurt here.", "field": "crashes.cyclist_injured",
              "record_value": 3, "claimed_value": None}
    assert T.verify_false(FX, absent)


def test_true_paraphrases_must_state_the_record_value():
    assert T.verify_true(FX, {"claim": "29 pedestrians were injured.", "field": "crashes.pedestrian_injured", "record_value": 29})
    assert not T.verify_true(FX, {"claim": "30 pedestrians were injured.", "field": "crashes.pedestrian_injured", "record_value": 29})


def test_the_gate_judges_attacks_like_any_claim():
    assert T.judge(CASE, "R3", "Bruckner Boulevard & Hunts Point Avenue had 29 pedestrians killed.")
    assert not T.judge(CASE, "R3", "Bruckner Boulevard & Hunts Point Avenue had 29 pedestrians injured.")


def test_score_counts_only_verified_claims():
    rows = [{"kind": "false", "error_type": "wrong_label", "verified": True, "accepted": True},
            {"kind": "false", "error_type": "wrong_label", "verified": True, "accepted": False},
            {"kind": "false", "error_type": "rate_swap", "verified": False, "accepted": True},
            {"kind": "true", "verified": True, "accepted": False}]
    s = T.score(rows)
    assert s["false_claims"] == 2 and s["attack_success"] == 0.5 and s["false_refusal"] == 1.0
    assert s["dropped_unverified"] == 1 and s["by_type"]["wrong_label"]["accepted"] == 1
