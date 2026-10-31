from nearmisslens import bench


def test_verdicts_follow_the_stored_intervals():
    assert "not met" in bench._fusion_verdict({"t": {"top5_diff_fusion_minus_crash_ci95": [-0.1, 0.2]}})
    assert "rule met" in bench._fusion_verdict({"t": {"top5_diff_fusion_minus_crash_ci95": [0.01, 0.2]}})
    a = {"designs": {"x": {"calibrated_wilson95": [0.0, 0.08]}}}
    good = {"programs": [{"study": "T11", "part": "all sites", "calibrated": "reduced", "null_rank": 0.01}]}
    bad = {"programs": [{"study": "T11", "part": "all sites", "calibrated": "no_evidence", "null_rank": 0.13}]}
    assert "replaces the original gate" in bench._t14_verdict(a, good)
    assert "does not replace" in bench._t14_verdict(a, bad) and "(b) not met" in bench._t14_verdict(a, bad)
    t12 = {"summary": {"gate": {"rate": 0.055, "wilson95": [0.031, 0.096]}},
           "real": [{"label": "A", "claims": {"naive": "reduced", "gate": "no evidence"}, "gate": {"reason": "r"}},
                    {"label": "B", "claims": {"naive": "reduced", "gate": "reduced"}, "gate": {}}]}
    v = bench._t12_verdict(t12)
    assert "higher than" in v and "A (naive" in v and "B (naive" not in v
