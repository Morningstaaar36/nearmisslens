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
