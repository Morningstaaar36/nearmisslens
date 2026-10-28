import pandas as pd

from nearmisslens.pipeline import link_segments


def test_link_segments_joins_ids_across_overlap():
    rows = []
    for f in range(1, 21):
        rows.append({"id": "s0:a", "frame": f, "x": float(f), "y": 0.0, "cls": "vehicle", "segment": 0})
    for f in range(18, 40):
        rows.append({"id": "s1:b", "frame": f, "x": float(f) + 0.2, "y": 0.0, "cls": "vehicle", "segment": 1})
    out = link_segments(pd.DataFrame(rows), overlap_frames=3)
    assert out["id"].nunique() == 1
    assert not out.duplicated(["id", "frame"]).any()
    assert len(out) == 39
