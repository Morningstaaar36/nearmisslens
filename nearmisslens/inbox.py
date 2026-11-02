"""The live inbox: residents' reports from a city's Open311 feed (registry kind "inbox"), triaged by the crash record.

A report counts for the desk when it is about the street itself (signs, street defects, blocked walkways, curbs,
parking in the way) and sits within 50 m of a place with injury crashes in the city's own crash table. The desk then
works it like any other case; nothing is ever filed back to the city."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scipy.spatial import cKDTree

from . import context, opendata, treatments
from .config import SETTINGS


def adapter(city: str) -> dict | None:
    found = opendata.adapters_of(city, "inbox")
    return found[0] if found else None


def fetch(a: dict, days: int = 7, pages: int = 6) -> list[dict]:
    """Recent reports (cached per day, so a replay sees the same inbox)."""
    import httpx
    d = Path(SETTINGS.data_dir) / "inbox" / a["id"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{dt.date.today().isoformat()}.json"
    if path.exists() or SETTINGS.replay:
        files = sorted(d.glob("*.json"))
        return json.loads((path if path.exists() else files[-1]).read_text()) if (path.exists() or files) else []
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    with httpx.Client(headers=context.UA, timeout=60) as c:
        for page in range(1, pages + 1):
            r = c.get(a["endpoint"], params={"start_date": start, "page_size": 100, "page": page})
            if r.status_code != 200 or not r.json():
                break
            out += r.json()
    path.write_text(json.dumps(out))
    return out


def triage(city: str, reports: list[dict], radius_m: float = 50.0, years: int = context.YEARS,
           min_injury_crashes: int = 5) -> list[dict]:
    """Street reports with a photo near places with injury crashes, the most dangerous first."""
    a = adapter(city)
    org = treatments.origin(city)
    cr = treatments.crashes(city, org)
    last = int(cr["month"].max())
    inj = cr[(cr["month"] > last - 12 * years) & cr["injury"]]
    tree = cKDTree(inj[["x", "y"]].to_numpy())
    out = []
    for r in reports:
        if r.get("service_name") not in a["services"] or not r.get("media_url") or r.get("lat") is None:
            continue
        pt = treatments.xy([r["lat"]], [r["long"]], org)[0]
        n = len(tree.query_ball_point([float(pt[0]), float(pt[1])], radius_m))
        if n >= min_injury_crashes:
            out.append({**{k: r.get(k) for k in ("service_request_id", "service_name", "description", "address",
                                                  "lat", "long", "media_url", "requested_datetime", "status")},
                        "injury_crashes_within_50m": n, "window_years": years})
    return sorted(out, key=lambda x: -x["injury_crashes_within_50m"])


def task(r: dict, city: str) -> str:
    place = (opendata.city(city) or {}).get("name", city)
    return (f"A resident filed a 311 report on {r['requested_datetime'][:10]} ({r['service_name']}): "
            f"\"{r.get('description') or ''}\" at {r['address']}, {place} (lat {r['lat']}, lon {r['long']}); "
            f"photo: {r['media_url']}. Look at the photo, investigate the nearest intersection, say how urgent this is "
            "given the crash record there, and draft the work order to the agency that owns the road.")
