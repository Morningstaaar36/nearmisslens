"""NML-Bench T9: a citywide plan-gap screen of every New York City Vision Zero priority intersection from open data:
police-reported crashes nearby over five years and the city's Street Improvement Projects. The ranked list is for a
person to review: "no project" means none in the city's open project datasets within 150 m."""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import context, harm
from .evaluate import RESULTS_DIR

PRIORITY = "https://data.cityofnewyork.us/resource/tmt9-43em.json"
TOP_MEMOS = 20


def junctions() -> list[dict]:
    js, _ = context.fetch(PRIORITY, {"$limit": 5000})
    return [{"name": f"{r.get('street_1', '').title()} & {r.get('street_2', '').title()}", "lat": float(r["lat"]),
             "lon": float(r["long"])} for r in js if r.get("lat") and r.get("long")]


def screen(workers: int = 4) -> pd.DataFrame:
    def one(j):
        d = context.dossier(j["lat"], j["lon"], street=False)
        cr, pl = d.get("crashes") or {}, d.get("plans") or {}
        years = [p["year"] for p in pl.get("projects", []) if isinstance(p.get("year"), int)]
        return {**j, "since": cr.get("since"), "crashes": cr.get("crashes"), "injury_crashes": cr.get("injury_crashes"),
                "pedestrians_injured": cr.get("pedestrian_injured"), "cyclists_injured": cr.get("cyclist_injured"),
                "killed": sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed")),
                "projects_ever": len(years), "last_project_year": max(years) if years else None,
                "recent_projects": d.get("recent_projects"), "plan_gap": d.get("plan_gap"),
                "error": "; ".join(v["error"] for v in (cr, pl) if isinstance(v, dict) and "error" in v) or None}
    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, junctions()))
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


def write(df: pd.DataFrame, memos: list[dict] | None = None) -> dict:
    rows = json.loads(df.to_json(orient="records"))  # NaN becomes null, which browsers can parse
    since = df["since"].dropna()
    out = {"summary": {**summary(df), **(costed(distinct(df, since.iloc[0])) if len(since) else {})}, "rows": rows,
           "memos": memos or []}
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "citywide_nyc.json").write_text(json.dumps(out, indent=1, default=str))
    return out["summary"]
