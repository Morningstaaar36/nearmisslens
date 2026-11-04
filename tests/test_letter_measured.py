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


def test_a_letter_drafted_alone_counts_the_corners_own_crashes(monkeypatch):
    """The live page drafts a letter with a fresh desk: it must ask for the corner's own crashes, as the case did."""
    from nearmisslens import brief, engineer, letter
    asked = {}

    def dossier(lat, lon, corner=None):
        asked["corner"] = corner
        return {"crashes": {}}
    monkeypatch.setattr(engineer.context, "dossier", dossier)
    monkeypatch.setattr(brief, "fix_options", lambda d, cmf: {})
    monkeypatch.setattr(letter, "facts", lambda b, who=None, audience=None: {"to": "the city", "fixes": [],
                                                                             "addressed_to": []})
    monkeypatch.setattr(letter, "sources", lambda b, f: [])
    engineer.draft_request(engineer.Desk(), 40.7, -73.9, "A Street & B Street, Town", {"owners": []})
    assert asked["corner"] == "A Street & B Street"
