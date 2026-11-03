"""Independent test round 2: San Francisco's crash adapter left out the lighting, the primary collision factor, the
time and the road surface that DataSF records, so lighting was "not estimated: the record does not show crashes in
darkness". The fields are data in registry.json; a dataset's own word for "dark, street lights on" is too (no network)."""
from nearmisslens import opendata


def test_every_crash_adapter_with_these_columns_maps_them():
    sf = opendata.adapter("sf-crashes")
    for k in ("light_fields", "surface_fields", "factor_fields", "time_field"):
        assert sf.get(k), k


def test_a_datasets_own_word_for_lit_counts_as_lit(monkeypatch):
    a = {"id": "zz-crashes", "source": "zz", "date_field": "d", "injured": {"any": ["n"]}, "killed": {"any": ["k"]},
         "light_fields": ["lighting"], "lit_values": ["dark - street lights"], "surface_fields": ["road"]}
    rows = [{"d": "2026-01-01", "n": "1", "k": "0", "lighting": x, "road": "Dry"}
            for x in ("Dark - Street Lights", "Dark - Street Lights", "Dark - No Street Lights", "Daylight")]
    monkeypatch.setattr(opendata, "rows_near", lambda *a, **k: rows)
    s = opendata.crash_summary(a, 0, 0)
    assert s["dark_crashes"] == 3 and s["dark_lit_share"] == round(2 / 3, 3)
