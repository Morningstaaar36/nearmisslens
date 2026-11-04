"""A letter may quote the city's own measured effect of a fix (the causal gate's result): the checker must know those
figures as numbers, or every draft that quotes them is refused (found live on a newly searched corner)."""
from nearmisslens import context


def test_the_measured_effect_may_be_quoted_and_nothing_else():
    facts = {"junction": "A Street & B Street", "measured_in_this_city": {
        "fix": "a leading pedestrian interval",
        "result": "pedestrian injury crashes fell 17% (95% interval 11% to 22%)",
        "drop_pct": 17, "interval_low_drop_pct": 11, "interval_high_drop_pct": 22}}
    chk = context.FactCheck(facts)
    assert chk.text("Where the city installed it, pedestrian injury crashes fell 17% (95% interval 11% to 22%).") == []
    assert chk.text("Pedestrian injury crashes fell 45% where the city installed it.")
