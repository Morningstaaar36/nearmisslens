import base64

import cv2
import numpy as np

from nearmisslens import render, sam_api
from nearmisslens.calibrate import Calibration
from nearmisslens.segments import Detection


class FakeClient:
    def __init__(self):
        self.calls = []

    def cached(self, namespace, request, run, cost_fn, estimate, what, require_text=False, complete=None):
        self.calls.append(namespace)
        resp = run()
        assert complete is None or complete(resp)
        return resp

    def post_json(self, path, body):
        assert path == "/images/edits" and body["images"][0]["image_url"].startswith("data:image/png")
        img = np.full((512, 512, 3), 255, np.uint8)
        ok, buf = cv2.imencode(".png", img)
        return {"data": [{"b64_json": base64.b64encode(buf.tobytes()).decode()}], "output_format": "png"}


def test_pixels_metres_roundtrip():
    H = np.array([[0.5, 0.01, 10], [0.02, 0.5, 20], [0, 0, 1]], float)
    cal = Calibration(H, (100.0, 200.0, 0.1, 0.1), 0)
    px = np.array([[300.0, 400.0], [1200.0, 50.0]])
    assert np.allclose(cal.to_pixels(cal.to_metres(px)), px, atol=1e-6)


def test_render_composites_only_inside_disc_and_keeps_road_users(tmp_path, monkeypatch):
    frame = np.zeros((1200, 1600, 3), np.uint8)
    cal = Calibration(np.eye(3), (0.0, 0.0, 0.05, 0.05), 0)

    def fake_segment(client, image, concept, tag, dx=0.0, dy=0.0):
        if concept == "car":
            return [Detection(0, "1", "car", 500, 500, 540, 520, None, 0.9)]
        if concept == "crosswalk" and image.mean() > 10:
            m = np.zeros(image.shape[:2], np.uint8)
            m[480:560, 450:600] = 1
            return [Detection(0, "1", "crosswalk", 450, 480, 600, 560, m, 0.9)]
        return []

    monkeypatch.setattr(sam_api, "segment_image", fake_segment)
    centre_m = cal.to_metres(np.array([[800.0, 600.0]]))[0]
    out = render.render_fix(FakeClient(), frame, cal, tuple(centre_m), 10.0, "Crosswalk Visibility Enhancements",
                            {"prompt": "paint a crosswalk", "check": "crosswalk"}, tmp_path, "t")
    x0, y0, w, h = out["crop"]
    assert (w, h) == (1024, 1024) and out["radius_px"] == 200.0
    assert out["check_passed"] and out["area_before"] == 0 and out["protected_road_users"] == 1
    pair = cv2.imread(out["image"])
    after = pair[:, w:]
    assert after[620, 512].mean() > 200
    assert after[50, 50].mean() < 10
    assert after[510, 520].mean() < 30
