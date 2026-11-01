"""NML-Bench T9: a citywide plan-gap screen of every priority intersection a city lists in its open data (New York's
Vision Zero priority intersections in the registry):
police-reported crashes nearby over five years and the city's Street Improvement Projects. The ranked list is for a
person to review: "no project" means none in the city's open project datasets within 150 m."""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import context, harm
from .evaluate import RESULTS_DIR

TOP_MEMOS = 20


def junction_adapters(city: str) -> list[dict]:
    """Designation datasets that list a city's priority intersections as points (registry "junctions")."""
    from . import opendata
    return [a for a in opendata.adapters_of(city, "designation") if a.get("junctions")]


def cities() -> list[str]:
    """Cities the screen can run on: a priority-intersection list in the registry, or a "screen" setting that finds
    the worst corners from the city's own crash records."""
    from . import opendata
    return [c["id"] for c in opendata.load_cities() if junction_adapters(c["id"]) or (c.get("screen") or {}).get("from") == "crashes"]


def _named_roads(lat: float, lon: float, radius_m: int) -> list[dict]:
    q = f'[out:json][timeout:25];way(around:{radius_m},{lat},{lon})[highway][name];out tags;'
    try:  # a light query: only named roads near the point
        js, _ = context.overpass(q, timeout=40)
        return [e.get("tags", {}) for e in js.get("elements", [])]
    except Exception:
        try:  # the OSM API's map call for a box of the same size
            return [e.get("tags", {}) for e in context.osm_map(lat, lon, radius_m)
                    if e.get("type") == "way" and e.get("tags", {}).get("highway") and e["tags"].get("name")]
        except Exception:  # a name is a convenience; the coordinates are the corner
            return []


def corner_name(lat: float, lon: float, radii: tuple[int, ...] = (25, 50)) -> str:
    """'A & B' from the two most important named roads at the point (OpenStreetMap), for crash-found corners. A
    crash cluster's centre can sit a little off the junction, so the search widens until two streets are found."""
    rank = {"motorway": 0, "trunk": 0, "primary": 1, "secondary": 2, "tertiary": 3, "unclassified": 4, "residential": 5,
            "living_street": 6}
    names: list[str] = []
    for r in radii:
        roads = _named_roads(lat, lon, r)
        streets = [w for w in roads if w.get("highway") in rank or w.get("highway", "").endswith("_link")]
        named = sorted(streets or roads, key=lambda w: rank.get(w.get("highway"), 9))  # a footpath names no corner
        names = list(dict.fromkeys(w["name"] for w in named if w.get("name")))[:2]
        if len(names) == 2:
            break
    return " & ".join(names) if names else f"Corner at {lat:.5f}, {lon:.5f}"


def junctions_from_crashes(city: str, top: int = 50, radius_m: float = 50.0, years: int = 5) -> list[dict]:
    """The city's worst corners found from its own injury crashes: greedily the point with the most injury crashes
    within radius_m over the years to the as-of date, then the next at least 2 x radius_m away, and so on."""
    import numpy as np
    from scipy.spatial import cKDTree
    from . import treatments
    from .config import since
    org = treatments.origin(city)
    df = treatments.crashes(city, org)
    lo = since(years)
    df = df[(df["month"] >= lo.year * 12 + lo.month - 1) & df["injury"]]
    pts = df[["x", "y"]].to_numpy()
    if not len(pts):
        return []
    tree = cKDTree(pts)
    counts = np.array([len(n) for n in tree.query_ball_point(pts, radius_m)])
    alive = np.ones(len(pts), bool)
    out = []
    for i in np.argsort(-counts):
        if len(out) >= top:
            break
        if not alive[i]:
            continue
        near = tree.query_ball_point(pts[i], radius_m)
        cx, cy = pts[near].mean(axis=0)
        alive[tree.query_ball_point([cx, cy], 2 * radius_m)] = False
        lat = org[0] + cy / 110_574
        lon = org[1] + cx / (111_320 * np.cos(np.radians(org[0])))
        out.append({"lat": round(float(lat), 6), "lon": round(float(lon), 6)})
    for j in out:
        j["name"] = corner_name(j["lat"], j["lon"])
    return out


def junctions(city: str) -> list[dict]:
    from . import opendata
    cfg = (opendata.city(city) or {}).get("screen") or {}
    if cfg.get("from") == "crashes" and not junction_adapters(city):
        return junctions_from_crashes(city, cfg.get("top", 50), cfg.get("radius_m", 50.0))
    out = []
    for a in junction_adapters(city):
        j = a["junctions"]
        js, _ = context.fetch(a["endpoint"], {"$limit": 5000})
        out += [{"name": " & ".join(str(r.get(f, "")).title() for f in j["name_fields"]),
                 "lat": float(r[j["lat_field"]]), "lon": float(r[j["lon_field"]])}
                for r in js if r.get(j["lat_field"]) and r.get(j["lon_field"])]
    return out


def screen(city: str, workers: int = 4) -> pd.DataFrame:
    def one(j):
        d = context.dossier(j["lat"], j["lon"], street=False)
        cr, pl = d.get("crashes") or {}, d.get("plans") or {}
        years = [p["year"] for p in pl.get("projects", []) if isinstance(p.get("year"), int) and not p.get("planned")]
        return {**j, "since": cr.get("since"), "crashes": cr.get("crashes"), "injury_crashes": cr.get("injury_crashes"),
                "pedestrians_injured": cr.get("pedestrian_injured"), "cyclists_injured": cr.get("cyclist_injured"),
                "killed": sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed"))
                or cr.get("any_killed", 0),  # cities that record deaths without the mode
                "projects_ever": len(years), "last_project_year": max(years) if years else None,
                "recent_projects": d.get("recent_projects"), "plan_gap": d.get("plan_gap"),
                "error": "; ".join(v["error"] for v in (cr, pl) if isinstance(v, dict) and "error" in v) or None}
    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, junctions(city)))
    return pd.DataFrame(rows).sort_values("injury_crashes", ascending=False, na_position="last").reset_index(drop=True)


def distinct(df: pd.DataFrame, since: str) -> dict:
    """Crashes within 100 m of two priority intersections are in both rows, so the row sums count them twice; these
    totals count each crash once (from the same cached records)."""
    from . import opendata
    ok = df[df["error"].isna()]
    a = opendata.adapters_for(ok["lat"].iloc[0], ok["lon"].iloc[0], "crash")[0]
    inj, kil = a.get("injured", {}), a.get("killed", {})
    injury, killed = set(), {}
    for _, r in ok.iterrows():
        for x in opendata.rows_near(a, r["lat"], r["lon"], context.CRASH_RADIUS_M, dt.date.fromisoformat(since)):
            key = x.get("collision_id") or json.dumps(x, sort_keys=True, default=str)
            k = sum(opendata._sum(x, fs) for fs in kil.values())
            if k + sum(opendata._sum(x, fs) for fs in inj.values()) + opendata._sum(x, a.get("serious_injured", [])) > 0:
                injury.add(key)
            if k:
                killed[key] = k
    return {"since": since, "injury_crashes_distinct": len(injury), "killed_distinct": int(sum(killed.values()))}


def costed(d: dict) -> dict:
    """The distinct totals with their yearly cost at the U.S. DOT's injury-crash value (deaths not valued apart)."""
    return {**d, "harm_usd_per_year": round(d["injury_crashes_distinct"] / context.YEARS * harm.INJURY_CRASH_USD, -6),
            "harm_source": harm.BCA["source"]}


def summary(df: pd.DataFrame) -> dict:
    ok = df[df["error"].isna()]
    return {"intersections": len(df), "with_data": len(ok), "plan_gap": int(ok["plan_gap"].fillna(False).sum()),
            "plan_gap_share": float(ok["plan_gap"].fillna(False).mean()) if len(ok) else None,
            "injury_crashes_total": int(ok["injury_crashes"].fillna(0).sum()),
            "killed_total": int(ok["killed"].fillna(0).sum()),
            "median_injury_crashes": float(ok["injury_crashes"].median()) if len(ok) else None,
            "never_a_project": int((ok["projects_ever"] == 0).sum())}


def write(df: pd.DataFrame, memos: list[dict] | None = None, city: str | None = None) -> dict:
    if not city:
        raise ValueError("write() needs the registry city id the screen belongs to")
    rows = json.loads(df.to_json(orient="records"))  # NaN becomes null, which browsers can parse
    since = df["since"].dropna()
    out = {"summary": {**summary(df), **(costed(distinct(df, since.iloc[0])) if len(since) else {})}, "rows": rows,
           "memos": memos or []}
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"citywide_{city}.json").write_text(json.dumps(out, indent=1, default=str))
    return out["summary"]


def screened() -> list[tuple[str, dict]]:
    """The cities with a saved screen (results/bench/citywide_<city>.json), as (city, result)."""
    out = []
    for city in cities():
        p = RESULTS_DIR / "bench" / f"citywide_{city}.json"
        if p.exists():
            out.append((city, json.loads(p.read_text())))
    return out
