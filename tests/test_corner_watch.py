import shutil

import cv2
import numpy as np
import pytest

from nearmisslens import corner_watch as W
from nearmisslens.segments import Detection


def test_spark_present_needs_a_sam_detection_near_its_point():
    near = Detection(0, "1", "zebra crosswalk", 100, 100, 200, 150, None, 0.9)
    far = Detection(0, "1", "zebra crosswalk", 500, 400, 600, 450, None, 0.9)
    said = {"answer": "present", "points": [[150, 120]]}
    assert W.confirm(said, [near]) == "present"
    assert W.confirm(said, [far]) == "unsure"
    assert W.confirm({"answer": "absent", "points": []}, []) == "absent"
    assert W.confirm({"answer": "absent", "points": []}, [near]) == "unsure"


def test_dark_frames_are_left_out_by_rule(tmp_path):
    dark, light = tmp_path / "a.jpg", tmp_path / "b.jpg"
    cv2.imwrite(str(dark), np.full((48, 64, 3), 10, np.uint8))
    cv2.imwrite(str(light), np.full((48, 64, 3), 140, np.uint8))
    assert W.daylight([dark, light]) == [light]



def test_frames_outside_the_registry_daylight_hours_are_left_out(tmp_path):
    night, morning = tmp_path / "20261102T084500Z.jpg", tmp_path / "20261102T153000Z.jpg"
    assert W.in_hours([night, morning], {"collect_utc_hours": [14, 1]}) == [morning]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_packing_puts_a_black_frame_between_snapshots(tmp_path):
    paths = []
    for k in range(3):
        p = tmp_path / f"{k}.jpg"
        cv2.imwrite(str(p), np.full((48, 64, 3), 120 + k, np.uint8))
        paths.append(p)
    index = W.pack(paths, tmp_path / "out" / "c.mp4")
    assert index == [0, 2, 4]
    cap = cv2.VideoCapture(str(tmp_path / "out" / "c.mp4"))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert n == 6


def test_summary_scores_packing_and_ranks_only_rated_corners():
    rows = [{"id": str(k), "frames": 10, "injury_crashes": 50 - k, "rank_by_crashes": k + 1,
             "injury_crashes_per_1000_people_seen": float(k), "rank_by_exposure": 25 - k,
             "pack_check": [{"video": 3, "image": 3 + (k % 3 == 0) * 2}], "features": {"a": "present", "b": "unsure"}}
            for k in range(25)]
    s = W.summarize({"cameras": 25, "rows": rows})
    assert s["pack_checks"] == 25 and s["pack_within_1"] == 16 and not s["pack_rule_met"]
    assert s["ranking_reported"] and s["spearman_crash_vs_exposure"] == -1.0
    assert s["crash_top10_leaving_exposure_top10"] == 10 and s["features"]["present"] == 25
