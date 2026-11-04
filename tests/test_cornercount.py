"""T32's scorer: agreement within max(1, 15%), errors averaged over corners both counted, and a registered result is
never overwritten."""
import pytest

from nearmisslens import cornercount


def test_agreement_and_errors():
    spec = {"rule": {"min_agree": 2}}
    tool = [{"city": "a", "corner": "x", "tool_injury_crashes": 10, "circle_injury_crashes": 30},
            {"city": "a", "corner": "y", "tool_injury_crashes": 1, "circle_injury_crashes": 9},
            {"city": "a", "corner": "z", "error": "not found"}]
    ind = [{"injury_crashes": 11}, {"injury_crashes": 0}, {"injury_crashes": 5}]
    r = cornercount.compare(spec, tool, ind)
    assert [c["agree"] for c in r["comparison"]] == [True, True, False]
    assert r["summary"]["tool_agree"] == 2 and r["summary"]["rule_met"]
    assert r["summary"]["tool_mean_abs_error"] == 1.0 and r["summary"]["circle_mean_abs_error"] == 14.0


def test_a_registered_result_is_never_overwritten(monkeypatch, tmp_path):
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "experiment_T31b.json").write_text("{}")
    monkeypatch.setattr(cornercount, "RESULTS_DIR", tmp_path)
    with pytest.raises(FileExistsError):
        cornercount.run("T31b")
