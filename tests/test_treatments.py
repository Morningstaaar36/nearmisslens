import numpy as np
import pandas as pd
import pytest

from nearmisslens import harm, treatments as T


def _latlon(x, y):
    """Inverse of treatments._xy, to place synthetic sites and crashes in metres."""
    return (T.LAT0 + np.asarray(y) / 110_574,
            T.LON0 + np.asarray(x) / (111_320 * np.cos(np.radians(T.LAT0))))


def test_sites_merge_close_points_and_keep_earliest():
    lat, lon = _latlon([0, 20, 500], [0, 0, 0])
    s = T.sites(pd.DataFrame({"lat": lat, "lon": lon, "month": [100, 90, 95]}))
    assert len(s) == 2
    merged = s[s["points"] == 2].iloc[0]
    assert merged["month"] == 90 and abs(merged["x"] - 20) < 1


def test_window_sum_reads_any_start():
    mat = np.arange(12).reshape(2, 6)
    assert T._window_sum(mat, np.array([0, 2]), 3).tolist() == [0 + 1 + 2, 8 + 9 + 10]


def _city(effect=0.5):
    """Treated LPI sites (installed 2018-01) whose pedestrian crashes halve after the install, comparison sites
    installed in 2024 with a constant rate, a few turn-calming sites, and background crashes far from all of them."""
    m0, m1, install = 2012 * 12 + 6, 2026 * 12 + 9, 2018 * 12
    pts, crashes = [], []
    for k in range(20):
        pts.append((k * 1000.0, 0.0, install))
    for k in range(40):
        pts.append((k * 1000.0, 5000.0, 2024 * 12 + 5))
    turn = [(k * 1000.0, 10000.0, 2019 * 12 + 3) for k in range(5)]
    for x, y, m in pts + turn:
        for month in range(m0, m1 + 1):
            n = 2 if (x, y, m) not in pts[:20] or month < install else int(round(2 * effect))
            crashes += [(x + 10, y, month)] * n
    crashes += [(50_000.0, 50_000.0, month) for month in range(m0, m1 + 1) for _ in range(5)]
    c = np.array(crashes)
    xy = T._xy(*_latlon(c[:, 0], c[:, 1]))
    cr = pd.DataFrame({"month": c[:, 2].astype(int), "pedestrian": True, "injury": True, "motorist_only": False,
                       "x": xy[:, 0], "y": xy[:, 1]})
    to_df = lambda rows: pd.DataFrame({"lat": _latlon([r[0] for r in rows], [r[1] for r in rows])[0],
                                       "lon": _latlon([r[0] for r in rows], [r[1] for r in rows])[1],
                                       "month": [r[2] for r in rows]})
    return to_df(pts), to_df(turn), cr


def test_comparison_group_study_recovers_a_known_effect_and_a_null_placebo():
    lpi, turn, cr = _city(effect=0.5)
    out = T.analyse(lpi, turn, cr)
    main = out["lpi_not_yet_treated"]["pedestrian"]
    assert main["sites"] == 20 and main["theta"] == pytest.approx(0.5, abs=1e-6)
    assert out["lpi_not_yet_treated"]["excluded_neighbour_treatment"] == 0
    assert out["lpi_placebo_not_yet_treated"]["pedestrian"]["theta"] == pytest.approx(1.0, abs=1e-6)
    assert out["lpi_placebo_same_sites_not_yet_treated"]["pedestrian"]["sites"] == 20
    assert out["lpi_citywide"]["pedestrian"]["theta"] == pytest.approx(0.5, abs=1e-6)
    assert out["turn_calming_citywide"]["pedestrian"]["theta"] == pytest.approx(1.0, abs=1e-6)
    assert "_keep" not in out["lpi_not_yet_treated"]


def test_a_neighbouring_install_inside_the_window_excludes_the_site():
    lpi, turn, cr = _city()
    lat, lon = _latlon([60.0], [0.0])  # 60 m from the first treated site, installed one year after it
    lpi = pd.concat([lpi, pd.DataFrame({"lat": lat, "lon": lon, "month": [2019 * 12]})], ignore_index=True)
    out = T.analyse(lpi, turn, cr)
    assert out["lpi_not_yet_treated"]["excluded_neighbour_treatment"] >= 1
    assert out["lpi_not_yet_treated"]["pedestrian"]["sites"] < 21


def test_harm_values_follow_usdot_and_scale_non_injury_groups():
    assert harm.present_value_factor(10, 0.07) == pytest.approx(7.0236, abs=1e-3)
    inj = harm.option(2.0, "pedestrian-involved injury crashes", {"injury_crashes": 10, "crashes": 40})
    assert inj["harm_avoided_usd_per_year"] == round(2.0 * harm.INJURY_CRASH_USD, -3)
    rear = harm.option(2.0, "rear-end crashes", {"injury_crashes": 10, "crashes": 40})
    assert rear["injury_crashes_avoided_per_year"] == 0.5
    j = harm.junction({"injury_crashes": 50, "pedestrian_killed": 1}, 5)
    assert j["usd_per_year"] == round(10 * harm.INJURY_CRASH_USD, -3) and j["deaths_in_record"] == 1


def test_local_evidence_only_where_it_was_tested():
    assert T.local_evidence("dc", "Leading Pedestrian Interval") is None
    assert T.local_evidence("nyc", "Lighting") is None


def test_a_fix_already_installed_is_listed_not_proposed():
    from nearmisslens import brief
    d = {"city": "nyc", "crashes": {"crashes": 100, "injury_crashes": 50, "crash_type_recorded": False,
                                    "crash_groups": {"pedestrian": 20}, "factor_counts": {"Failure to Yield Right-of-Way": 20}},
         "plans": {"projects": [{"name": "Leading Pedestrian Interval signal", "year": 2008, "dataset": "nyc-lpi"}]},
         "street": {"signals": 2}}
    from nearmisslens.countermeasures import load_cmf
    o = brief.fix_options(d, load_cmf())
    assert all(x["countermeasure"] != "Leading Pedestrian Interval" for x in o["options"])
    assert o["in_place"] == [{"countermeasure": "Leading Pedestrian Interval", "year": 2008, "dataset": "nyc-lpi"}]
    assert "Already in place (city records): Leading Pedestrian Interval since 2008" in brief.fixes_table(o)


def test_letter_checker_rejects_an_invented_number_and_adds_sources(tmp_path, monkeypatch):
    import json
    from nearmisslens import letter
    from tests.test_agent import FakeClient, call, usage
    br = {"junction": "A Street & B Avenue, New York, NY",
          "dossier": {"city": "nyc", "years": 5, "lat": 40.8, "lon": -73.9,
                      "crashes": {"source": "NYC crashes", "since": "2021-10-30", "crashes": 300, "injury_crashes": 129,
                                  "pedestrian_injured": 29},
                      "plans": {"source": "NYC projects", "designated": True,
                                "projects": [{"name": "SIP", "year": 2015, "dataset": "nyc-sip-intersections"}]},
                      "plan_gap": True},
          "fixes": {"options": [{"countermeasure": "Medians and Pedestrian Refuge Islands", "cmf_id": "8799",
                                 "expected_crashes_avoided_per_year": 1.6, "targets": "pedestrian-involved injury crashes",
                                 "harm_avoided_usd_per_year": 561000.0, "break_even_cost_usd": 3939000.0,
                                 "verify_on_site": None}],
                    "harm": {"usd_per_year": 8834000.0}, "in_place": []}}
    to = [{"office": "Council Member, District 17, New York City Council", "district": 17, "source": "NYC districts"}]
    fc = FakeClient([
        {"id": "r1", "output": [call("finish", {"subject": "Safety at A Street", "body": "There were 140 injury crashes."}, "c1")],
         "usage": usage()},
        {"id": "r2", "output": [call("finish", {"subject": "Safety at A Street", "body":
            "There were 129 injury crashes, 29 pedestrians injured, about $8.8 million a year in harm. Refuge islands "
            "(CMF 8799) would avoid 1.6 a year and pay for themselves under $3.9 million. [Your name] [Your address]"}, "c2")],
         "usage": usage()}])
    res = letter.draft(fc, br, to)
    assert res["rejected_drafts"] == 1 and res["letter"].startswith("To: Council Member, District 17")
    assert "FHWA CMF Clearinghouse, CMF 8799" in res["letter"] and "sends nothing" in res["letter"]
    assert "140" not in res["letter"]
