import json

import pandas as pd

from nearmisslens import baseline


def ev(rows):
    return pd.DataFrame(rows, columns=["t", "cls_1", "cls_2"])


def test_score_matches_pair_and_time_one_to_one():
    ref = ev([(10.0, "vehicle", "two_wheeler"), (10.5, "vehicle", "two_wheeler"), (40.0, "vehicle", "pedestrian")])
    pred = ev([(10.2, "two_wheeler", "vehicle"), (41.5, "vehicle", "pedestrian"), (60.0, "vehicle", "vehicle")])
    s = baseline.score(pred, ref)
    assert s["tp"] == 1 and s["precision"] == 1 / 3 and s["recall"] == 1 / 3
    both = baseline.score(ev([(10.1, "vehicle", "two_wheeler"), (10.6, "vehicle", "two_wheeler")]), ref)
    assert both["tp"] == 2


def test_score_handles_empty_sets():
    ref = ev([(1.0, "vehicle", "vehicle")])
    assert baseline.score(ev([]), ref)["recall"] == 0 and baseline.score(ev([]), ref)["f1"] == 0
    assert baseline.score(ev([(1.0, "vehicle", "vehicle")]), ev([]))["tp"] == 0


def test_windows_follow_the_registration():
    assert len(baseline.windows(600.0)) == 60 and baseline.windows(600.0)[-1] == 590.0
    assert baseline.windows(25.0) == [0.0, 10.0]


def test_ask_sends_video_with_strict_schema(tmp_path):
    clip = tmp_path / "w.mp4"
    clip.write_bytes(b"video")

    class FakeClient:
        payloads = []

        def cached(self, namespace, request, run, cost_fn, estimate, what, require_text=False, complete=None):
            assert namespace == "b0" and request["schema"] == baseline.SCHEMA
            return run()

        def upload_file(self, path, expire_seconds=0):
            return "file-1"

        def create_response(self, payload):
            self.payloads.append(payload)
            return {"status": "completed", "output_text": json.dumps(
                {"near_misses": [{"t_s": 3.2, "road_user_1": "vehicle", "road_user_2": "pedestrian", "description": "x"}]})}

    fc = FakeClient()
    out = baseline.ask(fc, clip, "t")
    assert out[0]["t_s"] == 3.2
    assert fc.payloads[0]["input"][0]["content"][0] == {"type": "input_video", "file_id": "file-1"}
