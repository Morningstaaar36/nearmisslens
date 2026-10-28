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


def test_link_segments_is_one_to_one():
    rows = []
    for f in range(1, 21):
        rows.append({"id": "s0:a", "frame": f, "x": float(f), "y": 0.0, "cls": "vehicle", "segment": 0})
        rows.append({"id": "s0:b", "frame": f, "x": float(f), "y": 1.0, "cls": "vehicle", "segment": 0})
    for f in range(18, 40):
        rows.append({"id": "s1:c", "frame": f, "x": float(f), "y": 0.5, "cls": "vehicle", "segment": 1})
    out = link_segments(pd.DataFrame(rows), overlap_frames=3)
    assert out[out["frame"] == 5]["id"].nunique() == 2


def test_fast_parser_matches_official_parser():
    import glob
    import gzip
    import json
    import os

    import pytest

    from nearmisslens.config import SETTINGS
    from nearmisslens.meta_client import output_text
    from nearmisslens.segments import decode_masks, parse_fast, parse_text

    files = sorted(glob.glob(str(SETTINGS.cache_dir / "sam_video" / "*" / "*.json.gz")), key=os.path.getsize)
    files = [f for f in files if os.path.getsize(f) > 1000]
    if not files:
        pytest.skip("no cached SAM video responses")
    text = output_text(json.loads(gzip.decompress(open(files[0], "rb").read())))
    text = "\n".join(text.split("\n")[:30]) + "\n"
    official = parse_text(text, "car", video=True)
    fast = parse_fast(text, "car")
    assert len(fast) == len(official)
    decode_masks(fast, workers=1)
    for a, b in zip(sorted(fast, key=lambda d: (d.frame, d.obj)), sorted(official, key=lambda d: (d.frame, d.obj))):
        assert (a.frame, a.obj, a.x1, a.y1, a.x2, a.y2) == (b.frame, b.obj, b.x1, b.y1, b.x2, b.y2)
        assert (a.mask == b.mask).all()


def test_tile_clip_names_are_unique_per_crop(tmp_path, monkeypatch):
    from nearmisslens import tiling, video

    made = []
    monkeypatch.setattr(video, "probe", lambda p: {"width": 3840, "height": 2160, "fps": 10.0, "frames": 100})
    monkeypatch.setattr(video, "cut", lambda src, out, *a, **k: made.append(out.name) or out)
    monkeypatch.setattr(tiling, "source_sha", lambda p: "sha")
    monkeypatch.setattr(tiling.sam_api, "track_video", lambda *a, **k: [])

    class C:
        class meter:
            @staticmethod
            def check(*a):
                pass

    tiles = tiling.grid(3840, 2160)
    for t in tiles:
        tiling.track_tiles(C, tmp_path / "v.mp4", 0.0, 10.0, ["car"], tmp_path, [t])
    assert len(set(made)) == len(tiles)


def _fake_sam(n_objects_by_start):
    """SAM stand-in: n objects moving right at 2 px/frame, present in every frame of the requested window."""
    from nearmisslens.segments import Detection

    def track_video(client, clip, concept, frames, tag, dx=0.0, dy=0.0, source_key=None):
        start = float(source_key.split("start=")[1].split("|")[0])
        n = n_objects_by_start(start, frames)
        out = []
        for f in range(frames):
            g = int(round(start * 10)) + f
            for i in range(min(n, 16)):
                x = dx + 50 + 60 * i + 2 * g
                out.append(Detection(f, str(i), concept, x, dy + 100, x + 20, dy + 140, None, 0.9))
        return out
    return track_video


def test_saturated_requests_split_in_time_and_relink(tmp_path, monkeypatch):
    from nearmisslens import tiling, video

    monkeypatch.setattr(video, "probe", lambda p: {"width": 3840, "height": 2160, "fps": 10.0, "frames": 1000})
    monkeypatch.setattr(video, "cut", lambda src, out, *a, **k: out)
    monkeypatch.setattr(tiling, "source_sha", lambda p: "sha")
    monkeypatch.setattr(tiling.sam_api, "track_video", _fake_sam(lambda start, frames: 20 if frames > 60 else 10))

    class C:
        class meter:
            @staticmethod
            def check(*a):
                pass

    stats = {}
    dets = tiling.track_tiles(C, tmp_path / "v.mp4", 0.0, 10.0, ["car"], tmp_path, [(0, 0, 1984, 1144)], stats=stats)
    assert stats["splits"] == 1 and stats["requests"] == 3
    frames = sorted({d.frame for d in dets})
    assert frames == list(range(100))
    assert len({d.obj for d in dets}) == 10
    assert all(sum(1 for d in dets if d.frame == f) == 10 for f in frames)


def test_unsaturated_request_is_not_split(tmp_path, monkeypatch):
    from nearmisslens import tiling, video

    monkeypatch.setattr(video, "probe", lambda p: {"width": 3840, "height": 2160, "fps": 10.0, "frames": 1000})
    monkeypatch.setattr(video, "cut", lambda src, out, *a, **k: out)
    monkeypatch.setattr(tiling, "source_sha", lambda p: "sha")
    monkeypatch.setattr(tiling.sam_api, "track_video", _fake_sam(lambda start, frames: 8))

    class C:
        class meter:
            @staticmethod
            def check(*a):
                pass

    stats = {}
    tiling.track_tiles(C, tmp_path / "v.mp4", 0.0, 10.0, ["car"], tmp_path, [(0, 0, 1984, 1144)], stats=stats)
    assert stats == {"requests": 1}
