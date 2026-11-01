from nearmisslens import studyrequests as S

A = {"fields": {"main": "mainstreet", "cross": ["crossstreet1", "crossstreet2"], "type": "requesttype",
                "status": "statusdescription", "requested": "daterequested", "status_date": "statusdate",
                "id": "referencenumber"},
     "denied_when_status_has": "Denial", "fix_requests": {"Leading Pedestrian Interval": "Leading Pedestrian Interval"}}


def _case(name, in_place=(), ped=12):
    return {"junction": {"name": f"{name}, New York City"},
            "findings": {"choose_fixes": {"crashes": {"injury_crashes": 40, "pedestrian_injured": ped, "since": "2021-10-31"},
                                          "in_place": [{"countermeasure": c} for c in in_place]},
                         "test_programs": {"projects_here": []}}}


def _req(main, cross, kind="Leading Pedestrian Interval", status="Study Request Denial", decided="2009-02-06"):
    return {"mainstreet": main, "crossstreet1": cross, "requesttype": kind, "statusdescription": status,
            "daterequested": "2008-10-01T00:00:00.000", "statusdate": f"{decided}T00:00:00.000", "referencenumber": "X1"}


def test_street_names_normalise_across_spellings():
    assert S.norm("West 125th Street") == S.norm("W 125 ST") == "W 125 ST"
    assert S.norm("Kissena Blvd.") == S.norm("KISSENA BOULEVARD")


def test_a_denied_fix_still_missing_with_pedestrians_hurt_since_is_a_rerequest():
    idx = S.index(A, [_req("MAIN STREET", "KISSENA BOULEVARD")])
    c = S.corner(A, idx, _case("Main Street & Kissena Boulevard"))
    ask = S.rerequest(c)
    assert ask and ask["text"] and not ask["refused"] and "12 pedestrians injured" in ask["text"]
    assert "2009-02-06" in ask["text"]


def test_no_rerequest_when_the_fix_is_now_there_or_the_request_was_approved_or_after_the_window_start():
    idx = S.index(A, [_req("MAIN STREET", "KISSENA BOULEVARD")])
    assert S.rerequest(S.corner(A, idx, _case("Main Street & Kissena Boulevard",
                                              in_place=("Leading Pedestrian Interval",)))) is None
    approved = S.index(A, [_req("MAIN STREET", "KISSENA BOULEVARD", status="LPI Approval")])
    assert S.rerequest(S.corner(A, approved, _case("Main Street & Kissena Boulevard"))) is None
    late = S.index(A, [_req("MAIN STREET", "KISSENA BOULEVARD", decided="2023-05-01")])
    assert S.rerequest(S.corner(A, late, _case("Main Street & Kissena Boulevard"))) is None


def test_unmatched_corners_are_left_out_not_guessed():
    idx = S.index(A, [_req("MAIN STREET", "KISSENA BOULEVARD")])
    assert S.corner(A, idx, _case("Main Street & Roosevelt Avenue")) is None
