import subprocess

import numpy as np
import pandas as pd
import pytest

from nearmisslens import conflicts as cf
from nearmisslens import match, tiling, video
from nearmisslens.meta_client import IncompleteResponse, MetaClient, collect_stream
from nearmisslens.segments import Detection
from tests.test_conflicts import track

TILES = [(0, 0, 1100, 1000), (900, 0, 1100, 1000)]


def det(frame, obj, x, payload=None):
    return Detection(frame, obj, "car", x, 500, x + 20, 520, None, 0.9, payload)


def test_merge_tiles_keeps_mask_payload():
    dets = [det(f, "t0:1", 1000, ("H", "data", 1, 1)) for f in range(5)]
    dets += [det(f, "t1:7", 1001, ("H", "data", 1, 1)) for f in range(5)]
    merged = tiling.merge_tiles(dets, TILES)
    assert len({d.obj for d in merged}) == 1
    assert all(d.payload is not None for d in merged)


def test_merge_tiles_is_one_to_one_per_tile_pair():
    dets = []
    for f in range(5):
        dets += [det(f, "t0:A", 1000), det(f, "t0:C", 1012), det(f, "t1:B", 1006)]
    merged = tiling.merge_tiles(dets, TILES)
    assert all(sum(1 for d in merged if d.frame == f) == 2 for f in range(5))


def test_stream_without_completion_is_not_cached(tmp_path):
    out = collect_stream(iter([{"type": "response.output_text.delta", "delta": "<0f>partial"}]))
    assert out["status"] == "stream_ended"
    from nearmisslens.config import Settings
    client = MetaClient(Settings(cache_dir=tmp_path / "c", runs_dir=tmp_path / "r"))
    with pytest.raises(IncompleteResponse):
        client.cached("ns", {"a": 1}, lambda: out, lambda r: (0.0, "sam-3.1", {}), 0.01, "t")
    assert not list((tmp_path / "c").rglob("*.gz"))


def test_pet_compares_non_adjacent_occupants():
    a = track(1, -20, 0, 10, 0, n=60)
    b = track(2, -25, 0, 10, 0, n=60)
    c = track(3, 0, -10, 0, 10, n=60, cls="pedestrian", length=0.6, width=0.6)
    pet = cf.pet_events(pd.concat([a, b, c]))
    pairs = {(r.id_1, r.id_2) for r in pet.itertuples()}
    assert (1, 3) in pairs and (2, 3) in pairs and (1, 2) not in pairs
    assert {"x", "y", "angle", "simultaneous"} <= set(pet.columns)
    assert pet["id_1"].dtype == a["id"].dtype and pet["id_2"].dtype == a["id"].dtype


def test_pet_overlapping_occupancy_is_zero():
    a = track(1, -20, 0, 10, 0, n=50)
    b = track(2, 0, -20, 0, 10, n=50)
    pet = cf.pet_events(pd.concat([a, b]))
    row = pet.iloc[0]
    assert row["pet"] == 0 and bool(row["simultaneous"])


def test_idf1_is_one_to_one():
    rows = []
    for f in range(1, 21):
        rows.append({"id": "r1" if f <= 10 else "r2", "frame": f, "x": float(f), "y": 0.0, "cls": "vehicle"})
    ref = pd.DataFrame(rows)
    pred = ref.assign(id="p1")
    m = match.tracking_metrics(pred, ref, "vehicle", fps=10.0)
    assert m["idf1"] == pytest.approx(0.5)


def test_cut_leaves_no_file_when_ffmpeg_fails(tmp_path):
    out = tmp_path / "x.mp4"
    with pytest.raises(subprocess.CalledProcessError):
        video.cut(tmp_path / "missing.mp4", out, 0.0, 1.0)
    assert not list(tmp_path.iterdir())


def test_conductor_rejects_out_of_range_jobs():
    from nearmisslens import conductor
    site = conductor.Site(None, None, 10.0, 3840, 2160, tiling.grid(3840, 2160), 30.0, 90.0, None)
    led = conductor.Ledger(1.0)
    for t, w in ((-1, 0), (0, -1), (4, 0), (0, 3)):
        assert conductor.run_job(None, site, led, t, w, "car")["status"] == "rejected"
    assert led.spent_usd == 0 and not led.jobs
