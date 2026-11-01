from nearmisslens import plan


def _opt(name, avoided, evidence, scale="low-cost", check=None):
    return {"countermeasure": name, "cmf_id": "1", "scale": scale, "evidence": evidence,
            "expected_crashes_avoided_per_year": avoided, "harm_avoided_usd_per_year": avoided * 342_400,
            "break_even_cost_usd": avoided * 2_400_000, "verify_on_site": check}


def _case(slug, options, owners=(("the city DOT", "recorded", "x"),), by_year=None, projects=(), injury=50):
    return {"_slug": slug, "asof": "2026-10-31",
            "junction": {"name": f"{slug} & B, Town", "lat": 40.0, "lon": -73.0},
            "findings": {
                "choose_fixes": {"options": options, "crashes": {"injury_crashes": injury, "by_year": by_year or {}},
                                 "harm": {"injury_crashes_per_year": injury / 5, "usd_per_year": injury / 5 * 342_400}},
                "test_programs": {"projects_here": [{"year": y} for y in projects], "repeat_risk": []},
                "who_must_act": {"owners": [{"party": p, "confidence": c, "basis": {"value": v}} for p, c, v in owners],
                                 "requesters": [{"party": "Board 1"}]},
                "root_cause": {"over_represented": []}}}


def test_one_supported_fix_per_corner_and_textbook_kept_apart():
    r = plan.corner(_case("a", [_opt("Yellow", 7.0, "needs a site check", check="timing below ITE"),
                                _opt("Backplates", 3.9, "FHWA-cited"), _opt("Roundabout", 18.0, "national studies",
                                                                              scale="reconstruction")]))
    assert r["best"]["countermeasure"] == "Backplates"       # the strongest tier, not the largest number
    assert r["textbook"]["countermeasure"] == "Yellow"        # largest low-cost estimate; reconstructions never count
    s = plan.summarize([r], {"factor": 0.9}, None)
    assert s["crashes_avoided_per_year_total"] == 3.9 and s["crashes_avoided_per_year_after_rtm"] == 3.5
    assert s["textbook_crashes_avoided_per_year"] == 7.0 and s["corners_where_textbook_fix_is_not_supported"] == 1


def test_totals_add_the_rows_and_corners_without_a_supported_fix_are_counted():
    rows = [plan.corner(_case("a", [_opt("LPI", 2.0, "measured here")])),
            plan.corner(_case("b", [_opt("Yellow", 5.0, "needs a site check", check="t")])),
            plan.corner(_case("c", []))]
    s = plan.summarize(rows, {"factor": None}, None)
    assert s["corners"] == 3 and s["corners_with_supported_fix"] == 1
    assert s["crashes_avoided_per_year_total"] == s["crashes_avoided_per_year_after_rtm"] == 2.0
    assert s["supported_by_tier"] == {"measured here": 1}


def test_agencies_split_and_presumed_owners_are_flagged():
    rows = [plan.corner(_case("a", [_opt("LPI", 2.0, "measured here")],
                              owners=(("the city DOT", "recorded", "x"), ("the state DOT", "recorded", "y")))),
            plan.corner(_case("b", [], owners=(("the county", "inferred", "no road-owner dataset"),)))]
    g = {x["party"]: x for x in plan.by_agency(rows)}
    assert g["the state DOT"]["intersections"] == 1 and not g["the state DOT"]["presumed"]
    assert g["the county"]["presumed"] and g["the county"]["intersections_with_supported_fix"] == 0


def test_agency_letter_is_number_checked_and_a_wrong_total_is_refused():
    rows = [plan.corner(_case("a", [_opt("LPI", 2.0, "measured here")], injury=60)),
            plan.corner(_case("b", [_opt("Backplates", 1.5, "FHWA-cited")], injury=40))]
    idx = {r["slug"]: r for r in rows}
    g = plan.by_agency(rows)[0]
    good = plan.agency_letter("nyc", g, idx, "2026-10-31")
    assert good["body"] and not good["refused"] and "100 injury crashes" in good["body"]
    from nearmisslens.context import FactCheck
    check = FactCheck(good["facts"])  # the record says 100 injury crashes and 3.5 avoided a year
    assert check.text("the 2 high-crash intersections had 120 injury crashes.")
    assert check.text("a fix would avoid about 9 crashes a year.")
    assert not check.text("the 2 high-crash intersections had 100 injury crashes.")


def test_regression_to_the_mean_is_measured_only_on_corners_without_a_project():
    by = lambda b, a: {"2022": b, "2023": b, "2024": a, "2025": a}
    rows = [plan.corner(_case(f"c{k}", [], by_year=by(10, 10))) for k in range(6)]
    rows += [plan.corner(_case("hot1", [], by_year=by(40, 30))), plan.corner(_case("hot2", [], by_year=by(40, 30))),
             plan.corner(_case("built", [], by_year=by(80, 10), projects=(2023,)))]
    r = plan.regression_to_mean(rows)
    assert r["corners"] == 8 and r["factor"] < 1      # the built corner is left out
    assert plan.regression_to_mean(rows[:3])["factor"] is None
