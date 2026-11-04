"""A corner's own crash count against an independent count (registered tests T31, T31b, T32).

    nml corner-count T32                                   the tool's counts for the spec's corners (no model, $0)
    nml corner-count T32 --independent FILE                the same, compared with an independent counter's file

The spec (validation/experiments/<ID>.json) lists the corners and the agreement rule. A corner in a city's saved screen
keeps the screen's junction point; any other corner is geocoded. The result goes to
validation/results/bench/experiment_<ID>.json and is never overwritten: a second run needs --out."""
from __future__ import annotations

import json

from . import brief, context
from .config import ROOT
from .evaluate import RESULTS_DIR

SPECS = ROOT / "validation" / "experiments"
DOCS_DATA = ROOT / "docs" / "data"


def _point(city: str, corner: str, city_name: str) -> tuple[float, float]:
    try:
        for c in json.loads((DOCS_DATA / city / "index.json").read_text())["corners"]:
            if c["name"] == corner:
                return c["lat"], c["lon"]
    except (OSError, KeyError, ValueError):
        pass
    lat, lon, _ = brief.geocode(f"{corner}, {city_name}")
    return lat, lon


def tool_counts(spec: dict) -> list[dict]:
    from . import opendata
    names = {c["id"]: c["name"] for c in opendata.load_cities()}
    rows = []
    for c in spec["corners"]:
        row = {"city": c["city"], "corner": c["corner"]}
        try:
            lat, lon = _point(c["city"], c["corner"], names.get(c["city"], c["city"]))
            own = context.dossier(lat, lon, street=False, corner=c["corner"])["crashes"]
            circle = context.dossier(lat, lon, street=False)["crashes"]
            row.update({"lat": lat, "lon": lon, "tool_injury_crashes": own.get("injury_crashes"),
                        "circle_injury_crashes": circle.get("injury_crashes"), "attribution": own.get("attribution")})
        except Exception as e:  # a corner the tool cannot find counts as not agreeing
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


def compare(spec: dict, tool: list[dict], independent: list[dict]) -> dict:
    rule = spec["rule"]
    out = []
    for t, i in zip(tool, independent):
        ind = i.get("injury_crashes")
        tol = max(1.0, 0.15 * ind) if ind is not None else None
        agree = lambda v: v is not None and ind is not None and abs(v - ind) <= tol
        out.append({"city": t["city"], "corner": t["corner"], "independent": ind,
                    "tool": t.get("tool_injury_crashes"), "circle": t.get("circle_injury_crashes"),
                    "agree": agree(t.get("tool_injury_crashes")), "circle_agree": agree(t.get("circle_injury_crashes"))})
    both = [r for r in out if r["tool"] is not None and r["independent"] is not None]
    mae = lambda k: round(sum(abs(r[k] - r["independent"]) for r in both if r[k] is not None) / len(both), 1) if both else None
    agree_n = sum(r["agree"] for r in out)
    return {"comparison": out, "summary": {
        "corners": len(out), "counted_by_both": len(both), "tool_agree": agree_n,
        "circle_agree": sum(r["circle_agree"] for r in out), "tool_mean_abs_error": mae("tool"),
        "circle_mean_abs_error": mae("circle"), "rule_met": agree_n >= rule["min_agree"]}}


def run(spec_id: str, independent: str | None = None, out: str | None = None) -> dict:
    spec = json.loads((SPECS / f"{spec_id}.json").read_text())
    path = RESULTS_DIR / "bench" / (out or f"experiment_{spec_id}.json")
    if path.exists() and out is None:
        raise FileExistsError(f"{path} exists (a registered result is never overwritten); pass --out NAME")
    res = {"id": spec_id, "spec": f"validation/experiments/{spec_id}.json", "tool": tool_counts(spec)}
    if independent:
        ind = json.loads((ROOT / independent).read_text())
        res["independent"] = independent
        res.update(compare(spec, res["tool"], ind))
    path.write_text(json.dumps(res, indent=1, default=str))
    return res
