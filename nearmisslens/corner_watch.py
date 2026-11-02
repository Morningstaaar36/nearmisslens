"""Corner Watch: what the city's own cameras show at its most dangerous intersections (NML-Bench T23).

Two Meta models, each doing what it is good at, under checks:
- SAM 3.1 counts people and vehicles in every daylight frame. Frames are packed into one video, with a black frame
  between snapshots so nothing carries over, because SAM's video mode costs $0.20 per 1,000 frames against $2.50 per
  1,000 images (adapter A8). A small sample is also counted in image mode to check that packing gives the same counts.
- Muse Spark, at low reasoning effort (adapter A2: seeing does not improve with more thinking), looks at one daylight
  frame per corner and points at what is there: a high-visibility crosswalk, a curb extension, a pedestrian refuge, a
  vehicle stopped in the crosswalk, a person crossing outside it. SAM 3.1 must find the same thing near Spark's point,
  or the answer is "unsure"; a dark or missing frame is "unsure" by rule (adapter A4: evidence or abstain).

What the city gains: crash counts ignore how many people use a corner. Counting them turns "most crashes" into "most
crashes per person crossing", and the frame shows whether the fix the evidence supports is already there."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import cameras, sam_api
from .config import SETTINGS
from .cost import token_usd
from .meta_client import output_text

from .config import MODELS
SPARK = MODELS["vision"]
DARK = 55.0  # mean grey level below which a frame is too dark to read (night)
FEATURES = {k: tuple(v) for k, v in json.loads((Path(__file__).resolve().parent / "data" / "corner_features.json").read_text())["features"].items()}
_item = {"type": "object", "additionalProperties": False, "required": ["answer", "points"],
         "properties": {"answer": {"type": "string", "enum": ["present", "absent", "unsure"]},
                        "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": list(FEATURES),
          "properties": {k: _item for k in FEATURES}}


def frames(cam_id: str, a: dict) -> list[Path]:
    d = Path(SETTINGS.data_dir) / "cameras" / a["id"] / "frames" / cam_id
    return sorted(d.glob("*.jpg"))


def brightness(img: np.ndarray) -> float:
    return float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())


def daylight(paths: list[Path]) -> list[Path]:
    """Frames bright enough to read; the rest are left out by rule, not guessed at."""
    out = []
    for p in paths:
        img = cv2.imread(str(p))
        if img is not None and brightness(img) >= DARK:
            out.append(p)
    return out


def pack(paths: list[Path], out: Path) -> list[int]:
    """The frames as one 1-fps video with a black frame between snapshots; returns each snapshot's video frame index."""
    out.parent.mkdir(parents=True, exist_ok=True)
    first = cv2.imread(str(paths[0]))
    h, w = first.shape[:2]
    tmp = out.with_suffix(".frames")
    tmp.mkdir(exist_ok=True)
    black = np.zeros_like(first)
    index, k = [], 0
    for p in paths:
        img = cv2.resize(cv2.imread(str(p)), (w, h))
        cv2.imwrite(str(tmp / f"{k:05d}.png"), img)
        index.append(k)
        cv2.imwrite(str(tmp / f"{k + 1:05d}.png"), black)
        k += 2
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmp / "%05d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()
    return index


def count_video(client, cam_id: str, paths: list[Path], concept: str, work: Path) -> list[int]:
    """Objects of `concept` in each snapshot, from one SAM 3.1 video request (at most 16 objects per frame)."""
    mp4 = work / f"{cam_id}.mp4"
    index = pack(paths, mp4)
    dets = sam_api.track_video(client, mp4, concept, 2 * len(paths), f"corner {cam_id}",
                               source_key=f"{cam_id}:" + ",".join(p.stem for p in paths))
    per = {}
    for d in dets:
        per.setdefault(d.frame, set()).add(d.obj)
    return [len(per.get(i, ())) for i in index]


def count_image(client, path: Path, concept: str) -> int:
    return len(sam_api.segment_image(client, cv2.imread(str(path)), concept, f"corner {path.parent.name}"))


def look(client, path: Path) -> dict:
    """Muse Spark's answer per feature, with points in image pixels (low reasoning effort)."""
    img = cv2.imread(str(path))
    url = sam_api.png_data_url(img)
    h, w = img.shape[:2]
    what = "; ".join(f"{k}: {v[0]}" for k, v in FEATURES.items())
    instructions = (f"This is a city traffic-camera image ({w}x{h} pixels) of an intersection. For each item, answer "
                    "present, absent or unsure, and give up to 4 [x, y] pixel points on what you see. Say unsure when "
                    f"glare, darkness or the camera angle hides it. Items: {what}.")
    request = {"model": SPARK, "image_sha": sam_api.hashlib.sha256(url.encode()).hexdigest(), "schema": SCHEMA,
               "instructions": instructions}
    payload = {"model": SPARK, "reasoning": {"effort": "low"}, "max_output_tokens": 4000, "instructions": instructions,
               "text": {"format": {"type": "json_schema", "name": "corner", "schema": SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": url}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(SPARK, u.get("input_tokens", 0), u.get("output_tokens", 0)), SPARK, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
    resp = client.cached("corner_look", request, lambda: client.create_response(payload), cost, 0.005,
                         f"corner look {path.parent.name}", require_text=True)
    return json.loads(output_text(resp))


def confirm(answer: dict, dets: list, near_px: float = 40.0) -> str:
    """Present only if a SAM 3.1 detection lies within near_px of one of Spark's points; absent only if both find
    nothing; otherwise unsure (evidence or abstain)."""
    pts = [p for p in answer.get("points") or [] if len(p) == 2]
    if answer.get("answer") == "present":
        for x, y in pts:
            for d in dets:
                if d.x1 - near_px <= x <= d.x2 + near_px and d.y1 - near_px <= y <= d.y2 + near_px:
                    return "present"
        return "unsure"
    if answer.get("answer") == "absent" and not dets:
        return "absent"
    return "unsure"


def watch(client, city: str, picks: list[dict], sample_images: int = 2) -> dict:
    """Counts, features and the exposure ranking for every picked camera with daylight frames."""
    a = cameras.adapter(city)
    work = Path(SETTINGS.data_dir) / "cameras" / a["id"] / "work"
    rows = []
    for cam in picks:
        paths = daylight(frames(cam["id"], a))
        if not paths:
            rows.append({**cam, "frames": 0, "note": "no daylight frame"})
            continue
        people = count_video(client, cam["id"], paths, "person", work)
        cars = count_video(client, cam["id"], paths, "car", work)
        check = [{"frame": p.stem, "video": people[i], "image": count_image(client, p, "person")}
                 for i, p in list(enumerate(paths))[:sample_images]]
        mid = paths[len(paths) // 2]
        ans = look(client, mid)
        feats = {k: confirm(ans.get(k) or {}, sam_api.segment_image(client, cv2.imread(str(mid)), FEATURES[k][1],
                                                                  f"corner {cam['id']}") if (ans.get(k) or {}).get(
            "answer") == "present" else []) for k in FEATURES}
        rows.append({**cam, "frames": len(paths), "people_per_frame": round(float(np.mean(people)), 2),
                     "vehicles_per_frame": round(float(np.mean(cars)), 2), "capped_frames": sum(c >= 16 for c in cars),
                     "pack_check": check, "frame_read": mid.stem, "spark": ans, "features": feats})
    seen = [r for r in rows if r.get("frames")]
    for r in seen:
        r["injury_crashes_per_1000_people_seen"] = round(1000 * r["injury_crashes"] / max(r["people_per_frame"] * r["frames"], 1), 2)
    by_crash = sorted(seen, key=lambda r: -r["injury_crashes"])
    by_exposure = sorted(seen, key=lambda r: -r["injury_crashes_per_1000_people_seen"])
    for k, r in enumerate(by_crash, 1):
        r["rank_by_crashes"] = k
    for k, r in enumerate(by_exposure, 1):
        r["rank_by_exposure"] = k
    return {"city": city, "cameras": len(picks), "with_daylight": len(seen), "rows": rows}
