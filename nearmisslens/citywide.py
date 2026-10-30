"""NML-Bench T9: a citywide plan-gap screen of every New York City Vision Zero priority intersection from open data:
police-reported crashes nearby over five years and the city's Street Improvement Projects. The ranked list is for a
person to review: "no project" means none in the city's open project datasets within 150 m."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import context
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
        return {**j, "crashes": cr.get("crashes"), "injury_crashes": cr.get("injury_crashes"),
                "pedestrians_injured": cr.get("pedestrian_injured"), "cyclists_injured": cr.get("cyclist_injured"),
                "killed": sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed")),
                "projects_ever": len(years), "last_project_year": max(years) if years else None,
                "recent_projects": d.get("recent_projects"), "plan_gap": d.get("plan_gap"),
                "error": "; ".join(v["error"] for v in (cr, pl) if isinstance(v, dict) and "error" in v) or None}
    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, junctions()))
    return pd.DataFrame(rows).sort_values("injury_crashes", ascending=False, na_position="last").reset_index(drop=True)


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
    out = {"summary": summary(df), "rows": rows, "memos": memos or []}
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "citywide_nyc.json").write_text(json.dumps(out, indent=1, default=str))
    return out["summary"]
