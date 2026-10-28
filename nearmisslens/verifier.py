from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .cache import file_sha256
from .cost import token_usd
from .meta_client import MetaClient, output_text

MODEL = "muse-spark-1.3-contributor"
CROP_W, CROP_H = 1280, 720
PAD_S = 3.0

VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["real_conflict", "evasive_action", "who_yielded", "confidence", "reason"],
    "properties": {
        "real_conflict": {"type": "boolean"},
        "evasive_action": {"type": "string", "enum": ["brake", "swerve", "both", "none", "unclear"]},
        "who_yielded": {"type": "string", "enum": ["A", "B", "neither", "unclear"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
}

INSTRUCTIONS = (
    "You review traffic near-miss candidates for a road safety audit. The clip is a top-down drone view. "
    "Road user A is outlined in red and B in cyan. A measured near-miss metric flagged this pair. "
    "Decide from the video whether it is a real traffic conflict: both users moving, on paths that would "
    "collide or nearly collide, typically with braking or swerving. Detection or tracking artefacts, "
    "queued vehicles, parked objects, a rider and their own two-wheeler, or users far apart are not real conflicts. "
    "Answer only from what is visible."
)


def _crop_window(px: np.ndarray, py: np.ndarray, width: int, height: int) -> tuple[int, int]:
    cx, cy = float(np.nanmean(px)), float(np.nanmean(py))
    x0 = int(np.clip(cx - CROP_W / 2, 0, width - CROP_W))
    y0 = int(np.clip(cy - CROP_H / 2, 0, height - CROP_H))
    return x0, y0


def render_event_clip(src: Path, out: Path, pixel_tracks: pd.DataFrame, id_a, id_b, frame_mid: int,
                      fps: float, width: int, height: int) -> Path:
    """Event-centred crop (±PAD_S) with both users outlined, re-encoded as H.264 MP4."""
    out = Path(out)
    if out.exists():
        return out
    half = int(PAD_S * fps)
    f0, f1 = max(1, frame_mid - half), frame_mid + half
    sel = pixel_tracks[pixel_tracks["frame"].between(f0, f1) & pixel_tracks["id"].isin([id_a, id_b])]
    sel = sel.dropna(subset=["px", "py", "box_l", "box_w", "box_angle"])
    x0, y0 = _crop_window(sel["px"].to_numpy(), sel["py"].to_numpy(), width, height)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                             f"{CROP_W}x{CROP_H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                             "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                            stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(str(src))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0 - 1)
    by_frame = {f: g for f, g in sel.groupby("frame")}
    for f in range(f0, f1 + 1):
        ok, img = cap.read()
        if not ok:
            break
        crop = img[y0:y0 + CROP_H, x0:x0 + CROP_W].copy()
        for r in by_frame.get(f, pd.DataFrame()).itertuples():
            colour = (0, 0, 255) if r.id == id_a else (255, 255, 0)
            half_l = max(6.0, r.box_l / 2)
            half_w = max(4.0, r.box_w / 2)
            box = cv2.boxPoints(((r.px - x0, r.py - y0), (2 * half_l, 2 * half_w), np.degrees(r.box_angle)))
            cv2.polylines(crop, [box.astype(np.int32)], True, colour, 3)
            cv2.putText(crop, "A" if r.id == id_a else "B", (int(r.px - x0) + 10, int(r.py - y0) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
        proc.stdin.write(crop.tobytes())
    cap.release()
    proc.stdin.close()
    proc.wait()
    return out


def speed_trace_png(states: pd.DataFrame, id_a, id_b, frame_mid: int, fps: float) -> str:
    h, w = 240, 640
    img = np.full((h, w, 3), 255, np.uint8)
    half = int(PAD_S * fps)
    for uid, colour in ((id_a, (0, 0, 255)), (id_b, (200, 160, 0))):
        g = states[(states["id"] == uid) & states["frame"].between(frame_mid - half, frame_mid + half)]
        if g.empty:
            continue
        sp = np.hypot(g["vx"], g["vy"]).to_numpy()
        xs = ((g["frame"].to_numpy() - (frame_mid - half)) / (2 * half) * (w - 40) + 20).astype(int)
        ys = (h - 20 - np.clip(sp / 15.0, 0, 1) * (h - 40)).astype(int)
        cv2.polylines(img, [np.stack([xs, ys], 1).astype(np.int32)], False, colour, 2)
    cv2.line(img, (w // 2, 10), (w // 2, h - 10), (120, 120, 120), 1)
    cv2.putText(img, "speed 0-15 m/s, red=A cyan=B, line=flagged moment", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


ARMS = ("full", "no_video", "no_metric")


def verify(client: MetaClient, clip: Path, trace_png: str, metric_text: str, tag: str,
           model: str = MODEL, effort: str = "low", arm: str = "full") -> dict:
    """arm: full (video + trace + metric), no_video (trace + metric), no_metric (video + trace)."""
    if arm not in ARMS:
        raise ValueError(arm)
    request = {"model": model, "clip": file_sha256(clip), "trace": trace_png[-64:], "metric": metric_text,
               "schema": VERDICT_SCHEMA, "effort": effort, "instructions": INSTRUCTIONS, "arm": arm}
    if arm == "full":
        request.pop("arm")

    def run():
        content = []
        if arm != "no_metric":
            content.append({"type": "input_text", "text": f"Flagged metric: {metric_text}"})
        else:
            content.append({"type": "input_text", "text": "A pair of road users was flagged by an automatic screen."})
        if arm != "no_video":
            content.append({"type": "input_video", "file_id": client.upload_file(clip, expire_seconds=24 * 3600)})
        content.append({"type": "input_image", "image_url": trace_png})
        payload = {"model": model, "instructions": INSTRUCTIONS, "reasoning": {"effort": effort},
                   "max_output_tokens": 4000,
                   "text": {"format": {"type": "json_schema", "name": "near_miss_verdict", "schema": VERDICT_SCHEMA,
                                       "strict": True}},
                   "input": [{"type": "message", "role": "user", "content": content}]}
        return client.create_response(payload)

    def cost(resp):
        u = resp.get("usage") or {}
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
        return token_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0), cached), model, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("spark_verify", request, run, cost, 0.01, f"verify {tag}")
    return json.loads(output_text(resp))
