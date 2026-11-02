"""Corner Watch: a city's public traffic cameras at its most dangerous intersections (registry kind "camera").

The camera list comes from the city's traveler map (no key). The cameras watched are the ones at intersections with the
most injury crashes in the city's own crash table, so every frame is of a corner that matters. Frames are fetched no
faster than the city refreshes them, kept only on this machine, and used for counts and for what the corner looks
like now: the site publishes counts and model answers only, never a frame (and so never a person).

Nothing here is a model: models read the frames in `corner_watch.py`, under the checks there."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from . import context, opendata, treatments
from .config import SETTINGS


def adapter(city: str) -> dict | None:
    found = opendata.adapters_of(city, "camera")
    return found[0] if found else None


def camera_list(a: dict) -> list[dict]:
    """Every camera the traveler map lists, with its intersection name and image URL (cached for a day)."""
    import httpx
    d = Path(SETTINGS.data_dir) / "cameras" / a["id"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / "list.json"
    if not path.exists() or time.time() - path.stat().st_mtime > 86400:
        if SETTINGS.replay:
            if not path.exists():
                raise FileNotFoundError(f"no saved camera list in {d}; run without replay first")
        else:
            with httpx.Client(headers=context.UA, timeout=60) as c:
                r = c.get(a["list_url"])
            r.raise_for_status()
            path.write_text(r.text)
    out = []
    for f in json.loads(path.read_text()).get("Features", []):
        lat, lon = f["PointCoordinate"]
        for cam in f.get("Cameras", []):
            if a.get("operator") and cam.get("Type") != a["operator"]:
                continue
            out.append({"id": cam["Id"], "name": cam["Description"], "lat": lat, "lon": lon,
                        "url": a["image_base"] + cam["ImageUrl"]})
    return out


def pick(city: str, n: int = 40, radius_m: float = 50.0, years: int = context.YEARS) -> list[dict]:
    """The n cameras at the intersections with the most injury crashes within radius_m in the last `years` years of
    the city's crash table; one camera per intersection (the first listed)."""
    a = adapter(city)
    cams = camera_list(a)
    org = treatments.origin(city)
    cr = treatments.crashes(city, org)
    last = int(cr["month"].max())
    recent = cr[(cr["month"] > last - 12 * years) & cr["injury"]]
    tree = cKDTree(recent[["x", "y"]].to_numpy())
    seen, rows = set(), []
    for cam in cams:
        key = (round(cam["lat"], 5), round(cam["lon"], 5))
        if key in seen:
            continue
        seen.add(key)
        pt = treatments.xy([cam["lat"]], [cam["lon"]], org)[0]
        idx = tree.query_ball_point([float(pt[0]), float(pt[1])], radius_m)
        ped = int(recent["pedestrian"].to_numpy()[idx].sum()) if idx else 0
        rows.append({**cam, "injury_crashes": len(idx), "pedestrian_injury_crashes": ped,
                     "window_months": 12 * years, "radius_m": radius_m})
    rows.sort(key=lambda r: (-r["injury_crashes"], r["id"]))
    return rows[:n]


def collect_once(picks: list[dict], a: dict, out: Path | None = None) -> dict:
    """One frame from each picked camera, skipped when the image has not changed since the last one kept."""
    import httpx
    out = out or Path(SETTINGS.data_dir) / "cameras" / a["id"] / "frames"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kept = same = failed = 0
    with httpx.Client(headers=context.UA, timeout=30) as c:
        for cam in picks:
            d = out / cam["id"]
            d.mkdir(parents=True, exist_ok=True)
            try:
                r = c.get(cam["url"])
                r.raise_for_status()
            except Exception:
                failed += 1
                continue
            h = hashlib.sha256(r.content).hexdigest()[:16]
            last = d / "last.sha"
            if last.exists() and last.read_text() == h:
                same += 1
                continue
            (d / f"{stamp}.jpg").write_bytes(r.content)
            last.write_text(h)
            with open(d / "index.jsonl", "a") as f:
                f.write(json.dumps({"t": stamp, "sha": h, "bytes": len(r.content)}) + "\n")
            kept += 1
    return {"t": stamp, "kept": kept, "unchanged": same, "failed": failed}


def daylight_utc_hours(a: dict) -> tuple[int, int]:
    """The UTC hours to collect in (the registry's local daylight window), so night frames are not fetched."""
    return tuple(a.get("collect_utc_hours", (14, 1)))


def in_window(hours: tuple[int, int], now: dt.datetime | None = None) -> bool:
    h = (now or dt.datetime.now(dt.timezone.utc)).hour
    lo, hi = hours
    return lo <= h < hi if lo < hi else (h >= lo or h < hi)


def collect(city: str, picks: list[dict], every_s: int = 600, until: float | None = None, log=print) -> None:
    """Collect every `every_s` seconds inside the daylight window until `until` (a unix time)."""
    a = adapter(city)
    hours = daylight_utc_hours(a)
    while until is None or time.time() < until:
        if in_window(hours):
            log(json.dumps(collect_once(picks, a)))
        time.sleep(max(every_s, a.get("refresh_s", 300)))
