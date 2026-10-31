from nearmisslens import rootcause as R

ADAPTER = {"id": "x", "city": "x", "source": "test", "injured": {"pedestrian": ["ped"], "motorist": ["mot"]},
           "killed": {"pedestrian": ["pedk"]}, "factor_fields": ["f1"], "time_field": "t",
           "vehicle_fields": ["v1"], "vehicle_groups": {"truck or bus": "truck|bus"}}


def _rows(n_ped, n_other, truck_every=0, hour="14:00"):
    rows = [{"ped": 1, "mot": 0, "f1": "Failure to Yield", "t": hour, "v1": "Sedan"} for _ in range(n_ped)]
    rows += [{"ped": 0, "mot": 1, "f1": "Unspecified", "t": hour, "v1": "Sedan"} for _ in range(n_other)]
    for i in range(0, len(rows), truck_every or len(rows) + 1):
        rows[i]["v1"] = "Box Truck"
    return rows


def _run(monkeypatch, rows, base_rows):
    counts, _, _ = R.profile(base_rows, ADAPTER)
    monkeypatch.setattr(R.opendata, "adapters_for", lambda lat, lon, kind: [ADAPTER])
    monkeypatch.setattr(R.opendata, "rows_near", lambda *a, **k: rows)
    monkeypatch.setattr(R, "baseline", lambda *a, **k: {"crashes": len(base_rows), "counts": dict(counts)})
    return R.analyse(0, 0)


def test_a_pattern_is_over_represented_only_above_the_city_baseline(monkeypatch):
    city = _rows(100, 900)                               # 10% of the city's crashes hurt a pedestrian
    out = _run(monkeypatch, _rows(30, 30), city)         # 50% here
    names = {t["pattern"] for t in out["over_represented"]}
    assert "a pedestrian hurt" in names
    same = _run(monkeypatch, _rows(6, 54), city)         # 10% here too
    assert "a pedestrian hurt" not in {t["pattern"] for t in same["over_represented"]}


def test_no_claims_from_few_crashes_and_missing_fields_are_listed(monkeypatch):
    out = _run(monkeypatch, _rows(5, 1), _rows(100, 900))
    assert not out["enough_crashes"] and out["over_represented"] == []
    assert "crash types" in out["not_recorded"]
    assert out["factor_unspecified_share"] == round(1 / 6, 3)
