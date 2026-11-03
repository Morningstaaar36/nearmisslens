"""Independent test round 2: a signal 70-100 m away (the next crossing) made an uncontrolled crossing "signalized", and
the memo then asked for signal fixes there. A signal counts as the junction's own only within 45 m, when that can be
asked; otherwise the 80 m count stands, as before (no network)."""
from nearmisslens import brief, context


def test_a_signal_at_the_next_crossing_does_not_make_the_junction_signalized():
    street = {"signals": 1, "stop_signs": 0, "roads": [{"name": "A St"}, {"name": "B Ave"}]}
    assert brief.site_control({"street": {**street, "signals_at_junction": 0}}) == "Uncontrolled"
    assert brief.site_control({"street": {**street, "signals_at_junction": 1}}) == "Signalized"
    assert brief.site_control({"street": street}) == "Signalized"  # a saved dossier from before: unchanged
    assert brief.site_control({"street": {**street, "signals_at_junction": None}}) == "Signalized"


def test_the_junction_signal_question_falls_back_when_it_cannot_be_asked(monkeypatch):
    def down(q, timeout=0):
        raise FileNotFoundError("not cached")
    monkeypatch.setattr(context, "overpass", down)
    monkeypatch.setattr(context, "osm_map", lambda lat, lon, r: [
        {"type": "node", "lat": 1.0001, "lon": 2.0, "tags": {"highway": "traffic_signals"}},   # about 11 m
        {"type": "node", "lat": 1.0008, "lon": 2.0, "tags": {"highway": "traffic_signals"}}])  # about 89 m
    assert context.signals_at_junction(1.0, 2.0) == 1
    monkeypatch.setattr(context, "osm_map", lambda lat, lon, r: (_ for _ in ()).throw(RuntimeError("down")))
    assert context.signals_at_junction(1.0, 2.0) is None
    monkeypatch.setattr(context, "overpass", lambda q, timeout=0: ({"elements": [{"id": 1}, {"id": 2}]}, 0.1))
    assert context.signals_at_junction(1.0, 2.0) == 2
