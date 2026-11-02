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

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import cameras, sam_api
from .config import SETTINGS
from .cost import token_usd
from .meta_client import output_text

from .config import DARK_MEAN as DARK, MODELS
SPARK = MODELS["vision"]
MIN_PEOPLE_SEEN = 20  # people counted over all frames below which a crashes-per-person rate is not computed
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


def in_hours(paths: list[Path], a: dict) -> list[Path]:
    """Frames whose UTC stamp (file name, %Y%m%dT%H%M%SZ) lies inside the registry's daylight hours; a night frame
    lit well enough to pass the brightness rule is still left out."""
    hours = cameras.daylight_utc_hours(a)
    return [p for p in paths if cameras.in_window(
        hours, dt.datetime.strptime(p.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc))]


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
        paths = daylight(in_hours(frames(cam["id"], a), a))
        if not paths:
            rows.append({**cam, "frames": 0, "note": "no daylight frame"})
            continue
        people = count_video(client, cam["id"], paths, "person", work)
        cars = count_video(client, cam["id"], paths, "car", work)
        check = [{"frame": p.stem, "video": people[i], "image": count_image(client, p, "person")}
                 for i, p in list(enumerate(paths))[:sample_images]]
        mid = paths[len(paths) // 2]
        ans = look(client, mid)
        img = cv2.imread(str(mid))
        feats = {}
        for k in FEATURES:  # SAM looks whenever Spark commits (present or absent): absent needs both to find nothing
            a_k = ans.get(k) or {}
            dets = sam_api.segment_image(client, img, FEATURES[k][1], f"corner {cam['id']}") \
                if a_k.get("answer") in ("present", "absent") else []
            feats[k] = confirm(a_k, dets)
        rows.append({**cam, "frames": len(paths), "people_per_frame": round(float(np.mean(people)), 2),
                     "vehicles_per_frame": round(float(np.mean(cars)), 2), "capped_frames": sum(c >= 16 for c in cars),
                     "pack_check": check, "frame_read": mid.stem, "spark": ans, "features": feats})
    seen = [r for r in rows if r.get("frames")]
    for r in seen:  # too few people seen gives no rate (never "riskiest" for having nobody in view)
        people = r["people_per_frame"] * r["frames"]
        r["people_seen"] = round(people)
        r["injury_crashes_per_1000_people_seen"] = round(1000 * r["injury_crashes"] / people, 2) \
            if people >= MIN_PEOPLE_SEEN else None
    by_crash = sorted(seen, key=lambda r: -r["injury_crashes"])
    by_exposure = sorted((r for r in seen if r["injury_crashes_per_1000_people_seen"] is not None),
                         key=lambda r: -r["injury_crashes_per_1000_people_seen"])
    for k, r in enumerate(by_crash, 1):
        r["rank_by_crashes"] = k
    for k, r in enumerate(by_exposure, 1):
        r["rank_by_exposure"] = k
    return {"city": city, "cameras": len(picks), "with_daylight": len(seen), "rows": rows}


def run_usd(ledger_rows: list[dict], start: float) -> float:
    """Meta $ of a watch run from the ledger: Spark's looks ("corner look ...") and SAM's requests ("sam video corner
    ...", "sam image corner ...") since `start`."""
    lab = re.compile(r"^(sam (video|image) )?corner ")
    return round(sum(r["usd"] for r in ledger_rows if r["t"] >= start and lab.match(str(r.get("what", "")))), 4)


def summarize(out: dict) -> dict:
    """T23's registered metrics: packed-video vs image counts, feature answers, and how counting people changes the
    ranking of corners."""
    from scipy.stats import spearmanr
    rows = [r for r in out["rows"] if r.get("frames")]
    checks = [c for r in rows for c in r.get("pack_check") or []]
    diffs = [abs(c["video"] - c["image"]) for c in checks]
    feats = [v for r in rows for v in (r.get("features") or {}).values()]
    rated = [r for r in rows if r.get("injury_crashes_per_1000_people_seen") is not None]
    rho = (spearmanr([r["rank_by_crashes"] for r in rated], [r["rank_by_exposure"] for r in rated]).statistic
           if len(rated) >= 3 else None)
    top = lambda key: {r["id"] for r in sorted(rated, key=lambda r: r[key])[:10]}
    return {"cameras": out["cameras"], "with_daylight": len(rows), "frames": sum(r["frames"] for r in rows),
            "pack_checks": len(checks), "pack_within_1": sum(d <= 1 for d in diffs),
            "pack_mean_abs_diff": round(sum(diffs) / len(diffs), 2) if diffs else None,
            "pack_rule_met": bool(diffs) and sum(d <= 1 for d in diffs) / len(diffs) >= 0.8,
            "features": {k: feats.count(k) for k in ("present", "absent", "unsure")},
            "with_rate": len(rated), "ranking_reported": len(rated) >= 20,
            "spearman_crash_vs_exposure": round(float(rho), 3) if rho is not None else None,
            "crash_top10_leaving_exposure_top10": len(top("rank_by_crashes") - top("rank_by_exposure"))
            if len(rated) >= 10 else None,
            "capped_frames": sum(r.get("capped_frames", 0) for r in rows)}
