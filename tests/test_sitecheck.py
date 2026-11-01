import numpy as np

from nearmisslens import sitecheck as S
from nearmisslens.segments import Detection

SHAPE = (768, 768, 3)


def det(x1, y1, x2, y2):
    return Detection(0, "o", "c", x1, y1, x2, y2, None, 0.9)


def test_gate_needs_both_models_to_agree():
    near = [det(380, 380, 400, 400)]  # at the centre
    assert S.decide({"answer": "present", "points": [[390, 390]]}, near, SHAPE)["gated"] == "present"
    assert S.decide({"answer": "present", "points": [[50, 50]]}, near, SHAPE)["gated"] == "unsure"  # SAM finds it elsewhere
    assert S.decide({"answer": "present", "points": [[390, 390]]}, [], SHAPE)["gated"] == "unsure"   # SAM finds nothing
    assert S.decide({"answer": "absent", "points": []}, [], SHAPE)["gated"] == "absent"
    assert S.decide({"answer": "absent", "points": []}, near, SHAPE)["gated"] == "unsure"           # SAM disagrees
    far = [det(0, 0, 30, 30)]  # outside the 40 m circle
    assert S.decide({"answer": "absent", "points": []}, far, SHAPE)["sam"] == "absent"


def test_score_counts_only_decided_corners_and_applies_the_rule():
    rows = []
    for k in range(10):
        ans = {a: {"spark": "present", "sam": "present", "gated": "present" if k < 8 else "unsure"} for a in S.ATTRS}
        rows.append({"answers": ans, "truth": {a: (k != 0) for a in S.ATTRS}})
    out = S.score(rows)
    g = out["bike_lane"]["gated"]
    assert g["decided"] == 8 and g["coverage"] == 0.8 and g["accuracy"] == 0.875
    assert out["bike_lane"]["used_in_product"] is True
    rows[1]["truth"] = {a: None for a in S.ATTRS}  # unknown truth is excluded
    assert S.score(rows)["median"]["gated"]["corners"] == 9


def test_wilson_interval():
    lo, hi = S.wilson(85, 100)
    assert 0.76 < lo < 0.78 and 0.90 < hi < 0.92


def test_osm_truth_reads_one_cached_tile_per_area(monkeypatch):
    from nearmisslens import context, sitecheck as S
    calls = []

    def fake(url, params=None, data=None, timeout=0):
        calls.append(data["data"])
        return {"elements": [{"lat": 40.75001, "lon": -73.98, "tags": {"crossing:markings": "ladder:skewed"}},
                             {"lat": 40.76, "lon": -73.98, "tags": {"crossing:markings": "lines"}}]}, 0.0
    monkeypatch.setattr(context, "fetch", fake)
    a = {"platform": "overpass", "osm_filter": "node[highway=crossing]", "tag": "crossing:markings",
         "yes_values": ["zebra", "ladder"]}
    assert S._truth_one(a, 40.75, -73.98, 40) is True        # ladder variant 1 m away
    assert S._truth_one(a, 40.7599, -73.98, 40) is False     # only plain lines within 40 m
    assert S._truth_one(a, 40.705, -73.95, 40) is None       # nothing tagged nearby: unknown, excluded
    assert all('["crossing:markings"]' in q and "around" not in q for q in calls)


def test_osm_api_truth_reads_a_box_around_the_point(monkeypatch):
    from nearmisslens import context, sitecheck as S
    seen = {}

    def fake(url, params=None, data=None, timeout=0):
        seen["url"], seen["bbox"] = url, params["bbox"]
        return {"elements": [
            {"type": "node", "lat": 40.75001, "lon": -73.98, "tags": {"highway": "crossing", "crossing:markings": "zebra"}},
            {"type": "node", "lat": 40.7501, "lon": -73.98, "tags": {"highway": "traffic_signals", "crossing:markings": "zebra"}},
            {"type": "way", "tags": {"highway": "footway"}}]}, 0.0
    monkeypatch.setattr(context, "fetch", fake)
    a = {"platform": "osm", "element": "node", "match": {"highway": "crossing"}, "tag": "crossing:markings",
         "yes_values": ["zebra", "ladder"]}
    assert S._truth_one(a, 40.75, -73.98, 40) is True
    w, s, e, n = map(float, seen["bbox"].split(","))
    assert seen["url"].endswith("/map.json") and s < 40.75 < n and w < -73.98 < e and (n - s) < 0.001


def test_osm_profile_falls_back_to_the_map_call_when_overpass_is_down(monkeypatch):
    from nearmisslens import context
    monkeypatch.setattr(context, "_OVERPASS_DOWN", ["refused"])
    lat, lon = 47.6, -122.33
    near = [{"type": "node", "id": 1, "lat": lat, "lon": lon, "tags": {"highway": "traffic_signals"}},
            {"type": "node", "id": 2, "lat": lat + 0.0015, "lon": lon, "tags": {"highway": "traffic_signals"}},  # 167 m
            {"type": "node", "id": 3, "lat": lat + 0.0015, "lon": lon, "tags": {"highway": "bus_stop"}},
            {"type": "way", "nodes": [1, 2], "tags": {"highway": "primary", "name": "1st Ave", "lanes": "4"}},
            {"type": "way", "nodes": [2], "tags": {"highway": "residential", "name": "Far St"}}]
    monkeypatch.setattr(context, "osm_map", lambda la, lo, r: near if r < 400 else
                        [{"type": "node", "id": 9, "lat": lat, "lon": lon + 0.003, "tags": {"amenity": "school"}}])
    o = context.osm(lat, lon)
    assert o["signals"] == 1 and o["bus_stops_200m"] == 1 and o["schools_400m"] == 1
    assert [r["name"] for r in o["roads"]] == ["1st Ave"]
