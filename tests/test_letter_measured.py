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


def test_the_live_letter_reads_the_corners_own_crashes_from_the_first_read(monkeypatch, tmp_path):
    """who_must_act reads the record before draft_request: the corner must be set before either, or the first read
    (the whole 100 m circle) is the one kept."""
    import json, socket, threading, time, urllib.request
    from nearmisslens import app, context, engineer
    corners_seen = []

    def who(desk, lat, lon, name):
        corners_seen.append(desk.corners.get((round(lat, 6), round(lon, 6))))
        return {"owners": []}, "R1"

    def draft(desk, lat, lon, name, who_, client):
        corners_seen.append(desk.corners.get((round(lat, 6), round(lon, 6))))
        return {"letter": "ok", "usd": 0.0}, "R2"
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(engineer, "who_must_act", who)
    monkeypatch.setattr(engineer, "draft_request", draft)
    monkeypatch.setattr(context, "city_of", lambda lat, lon: "zz")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    body = json.dumps({"name": "A Street & B Street, Town", "lat": 40.7, "lon": -73.9}).encode()
    for _ in range(100):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/letter", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                assert json.loads(r.read())["letter"] == "ok"
            break
        except OSError:
            time.sleep(0.05)
    assert corners_seen == ["A Street & B Street", "A Street & B Street"]


def test_a_death_counted_only_in_the_total_is_not_lost():
    """New York records some deaths in number_of_persons_killed with every mode at zero (a 2023 death at Lafayette St &
    E Houston St): the larger of the two counts is the deaths, so a letter never says no one was killed there."""
    from nearmisslens import context, opendata
    assert context.deaths({"pedestrian_killed": 0, "cyclist_killed": 0, "motorist_killed": 0, "any_killed": 1}) == 1
    assert context.deaths({"pedestrian_killed": 2, "any_killed": 3}) == 3
    assert context.deaths({"pedestrian_killed": 1}) == 1
    nyc = next(a for a in opendata.adapters_of("nyc", "crash") if a["id"] == "nyc-crashes")
    assert nyc["killed"].get("any") == ["number_of_persons_killed"]
