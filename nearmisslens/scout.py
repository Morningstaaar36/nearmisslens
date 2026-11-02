"""Scout agent: Muse Spark points at every road user of a kind in a tile; any point that no SAM 3.1 mask covers is a
road user SAM missed, and SAM is asked again with a point prompt there. The trial (registered go/no-go) measures
whether this raises recall against the reference on development frames."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import fluid, sam_api, tiling, video
from .cost import token_usd
from .meta_client import MetaClient, output_text
from .segments import parse_text
from .config import MODELS

MODEL = MODELS["reader"]
KINDS = {"two_wheeler": ("scooter", "motorcycle, scooter or moped with its rider"),
         "pedestrian": ("pedestrian", "person walking on foot (not riding)")}
COUNT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["points", "count"],
                "properties": {"count": {"type": "integer"}, "points": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["x", "y"],
                    "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}}}}}


def spark_points(client: MetaClient, image: np.ndarray, kind: str, tag: str) -> list[tuple[float, float]]:
    """Pixel positions (in the image sent) of every instance of the kind, from Muse Spark's count mode."""
    url = sam_api.png_data_url(image)
    prompt = (f'Point to every instance of "{KINDS[kind][1]}" in this top-down drone image of a road junction and '
              'count them. Do not miss small ones. Answer {"points": [{"x": <int>, "y": <int>}, ...], "count": <int>} '
              "with coordinates in the 0-1000 range.")
    request = {"model": MODEL, "prompt": prompt, "image": sam_api.hashlib.sha256(url.encode()).hexdigest()}
    payload = {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 6000,
               "text": {"format": {"type": "json_schema", "name": "count", "schema": COUNT_SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [
                   {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": url}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("scout_points", request, lambda: client.create_response(payload), cost, 0.005,
                         f"scout {tag} {kind}", require_text=True)
    h, w = image.shape[:2]
    pts = json.loads(output_text(resp))["points"]
    return [(min(max(p["x"], 0), 1000) * w / 1000, min(max(p["y"], 0), 1000) * h / 1000) for p in pts]


def point_prompt(points: list[tuple[float, float]], w: int, h: int) -> str:
    """SAM 3.1 object prompt: one object per point (at most 16 per request)."""
    objs = [f"{k + 1}<|point;x={int(round(x))};y={int(round(y))};w={w};h={h}|>" for k, (x, y) in enumerate(points[:16])]
    return "<0f>" + ",".join(objs)


def sam_points(client: MetaClient, image: np.ndarray, points: list[tuple[float, float]], tag: str) -> list:
    if not points:
        return []
    h, w = image.shape[:2]
    return sam_api.segment_image(client, image, point_prompt(points, w, h), tag)


def _covered(dets, x: float, y: float, pad: float = 4.0) -> bool:
    return any(d.x1 - pad <= x <= d.x2 + pad and d.y1 - pad <= y <= d.y2 + pad for d in dets)


def _match(centres: np.ndarray, ref: np.ndarray, tol_px: float) -> int:
    """One-to-one matches between predicted and reference centres within tol_px."""
    if not len(centres) or not len(ref):
        return 0
    from scipy.optimize import linear_sum_assignment
    D = np.linalg.norm(centres[:, None] - ref[None], axis=2)
    i, j = linear_sum_assignment(D)
    return int((D[i, j] <= tol_px).sum())


TRIAL_FRAMES = (601, 721, 841, 961, 1081)


def trial(client: MetaClient, kinds=("two_wheeler", "pedestrian"), frames=TRIAL_FRAMES, tol_px: float = 25.0) -> dict:
    """Go/no-go on development frames (2x2 tiles, 5 frames = 20 tiles): recall and precision against reference centres
    for SAM alone (concept prompt) and SAM + Scout (Spark points not covered by SAM, re-prompted as SAM points)."""
    c = fluid.clip(*fluid.DEV)
    info = video.probe(c.video)
    tiles = tiling.grid(info["width"], info["height"], 2, 2)
    ref_all = fluid.load_trajectories(c, real_only=True)
    out = {}
    for kind in kinds:
        concept = KINDS[kind][0]
        tot = {"ref": 0, "sam_pred": 0, "sam_tp": 0, "scout_pred": 0, "scout_tp": 0, "spark_points": 0, "added": 0}
        for f in frames:
            img = video.frame_at(c.video, f - 1)
            ref = ref_all[(ref_all["frame"] == f) & (ref_all["cls"] == kind)][["cx", "cy"]].to_numpy()
            for k, (x, y, tw, th) in enumerate(tiles):
                crop = img[y:y + th, x:x + tw]
                rin = ref[(ref[:, 0] >= x) & (ref[:, 0] < x + tw) & (ref[:, 1] >= y) & (ref[:, 1] < y + th)] - [x, y]
                sam = sam_api.segment_image(client, crop, concept, f"scout f{f} t{k}")
                pts = spark_points(client, crop, kind, f"f{f} t{k}")
                missed = [p for p in pts if not _covered(sam, *p)]
                extra = sam_points(client, crop, missed, f"scout points f{f} t{k} {kind}")
                cs = np.array([[(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2] for d in sam]).reshape(-1, 2)
                ce = np.array([[(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2] for d in extra]).reshape(-1, 2)
                both = np.vstack([cs, ce])
                tot["ref"] += len(rin)
                tot["sam_pred"] += len(cs)
                tot["sam_tp"] += _match(cs, rin, tol_px)
                tot["scout_pred"] += len(both)
                tot["scout_tp"] += _match(both, rin, tol_px)
                tot["spark_points"] += len(pts)
                tot["added"] += len(ce)
        r = lambda tp, n: tp / n if n else float("nan")
        res = {**tot, "sam_recall": r(tot["sam_tp"], tot["ref"]), "sam_precision": r(tot["sam_tp"], tot["sam_pred"]),
               "scout_recall": r(tot["scout_tp"], tot["ref"]), "scout_precision": r(tot["scout_tp"], tot["scout_pred"])}
        res["go"] = bool(res["scout_recall"] - res["sam_recall"] >= 0.10 and res["scout_precision"] >= 0.8)
        out[kind] = res
    return out
