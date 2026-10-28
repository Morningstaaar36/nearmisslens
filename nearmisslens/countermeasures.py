from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SETTINGS

CMF_PATH = SETTINGS.data_dir / "cmf" / "cmfclearinghouse.csv"
CMF_URL = "https://cmfclearinghouse.fhwa.dot.gov/cmf_datacsv.php?file=cmfclearinghouse.csv"

PAIR_CRASH_TYPES = {
    frozenset({"vehicle", "pedestrian"}): ["Vehicle/pedestrian"],
    frozenset({"two_wheeler", "pedestrian"}): ["Vehicle/pedestrian"],
}
CONFLICT_CRASH_TYPES = {"rear_end": ["Rear end"], "crossing": ["Angle", "Left turn"], "turning": ["Angle", "Left turn", "Right turn"],
                        "lane_change": ["Sideswipe"]}


def load_cmf(path: Path = CMF_PATH) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="latin-1", dtype=str, keep_default_na=False)
    df = pd.DataFrame({
        "crfid": raw["crfid"], "name": raw["cmName"], "category": raw["catname"], "subcategory": raw["subcatname"],
        "stars": pd.to_numeric(raw["qualRating"], errors="coerce"),
        "crf_pct": pd.to_numeric(raw["crfactor"], errors="coerce"),
        "cmf": pd.to_numeric(raw["accModFactor"], errors="coerce"),
        "crash_type": raw["crashType"], "severity": raw["crashSeverityKABCO"], "area": raw["areaType"],
        "control": raw["trafficControl"], "country": raw["country"], "citation": raw["citation"],
    })
    return df


def stars_label(stars: float) -> str:
    return f"{int(stars)}★" if stars == stars and stars >= 1 else "not rated"


def psc_items() -> list[dict]:
    return json.loads(resources.files("nearmisslens").joinpath("data/fhwa_psc.json").read_text())["items"]


def crash_types_for(pair: tuple[str, str], conflict_type: str) -> tuple[list[str], str]:
    """CMF crash types that correspond to a conflict, and a note when no road-user-specific type exists."""
    key = frozenset(pair)
    if key in PAIR_CRASH_TYPES:
        return PAIR_CRASH_TYPES[key], ""
    note = "no two-wheeler-specific crash type exists in the CMF Clearinghouse" if "two_wheeler" in pair else ""
    return CONFLICT_CRASH_TYPES.get(conflict_type, []), note


@dataclass
class Candidate:
    psc: str
    crfid: str
    name: str
    stars: str
    crf_pct: float
    cmf: float
    crash_type: str
    severity: str
    control: str
    note: str


def candidates(cmf: pd.DataFrame, pair: tuple[str, str], conflict_type: str, control: str | None = "Signalized",
               min_stars: int = 3, conditions: frozenset[str] = frozenset()) -> tuple[list[Candidate], list[dict]]:
    """FHWA PSC-linked CMFs that target the conflict's crash type and reduce crashes; rejections are returned with reasons.

    conditions names what the observed conflicts show (for example "a left-turn movement"); a countermeasure whose
    condition is not among them is rejected."""
    types, note = crash_types_for(pair, conflict_type)
    out: list[Candidate] = []
    rejected: list[dict] = []
    names = cmf["name"].str.lower()
    for item in psc_items():
        if not item["cmf_keywords"]:
            continue
        if control and item.get("site_control", "any") not in ("any", control):
            rejected.append({"psc": item["name"], "reason": f"applies to {item['site_control']} sites, not {control}"})
            continue
        if item.get("requires_user") and item["requires_user"] not in pair:
            rejected.append({"psc": item["name"], "reason": f"targets {item['requires_user']} crashes; no {item['requires_user']} in this conflict"})
            continue
        if item.get("condition") and item["condition"] not in conditions:
            rejected.append({"psc": item["name"], "reason": f"requires {item['condition']}, which the observed conflicts do not show"})
            continue
        hit = np.zeros(len(cmf), dtype=bool)
        for kw in item["cmf_keywords"]:
            hit |= names.str.contains(kw, regex=False).to_numpy()
        rows = cmf[hit]
        if rows.empty:
            continue
        typed = rows[rows["crash_type"].apply(lambda c: any(t in c.split(",") or t == c for t in types))]
        if typed.empty:
            rejected.append({"psc": item["name"], "reason": f"no CMF for crash type {types}"})
            continue
        if control:
            matched = typed[typed["control"].str.contains(control, case=False)]
            typed = matched if not matched.empty else typed
        worse = typed[typed["cmf"] >= 1]
        for r in worse.itertuples():
            rejected.append({"psc": item["name"], "crfid": r.crfid, "reason": f"CMF {r.cmf:.3f} >= 1 (no reduction) for {r.crash_type}"})
        for r in typed[typed["cmf"] <= 0].itertuples():
            rejected.append({"psc": item["name"], "crfid": r.crfid, "reason": f"CMF {r.cmf:.3f} is not a plausible estimate"})
        reducing = typed[(typed["cmf"] > 0) & (typed["cmf"] < 1)]
        good = reducing[reducing["stars"] >= min_stars]
        if good.empty:
            good = reducing[reducing["stars"].isna() | (reducing["stars"] < 1)]
        if good.empty:
            rejected.append({"psc": item["name"], "reason": f"no reducing CMF rated >= {min_stars} stars or unrated"})
            continue
        best = good.sort_values(["stars", "crf_pct"], ascending=False).iloc[0]
        out.append(Candidate(item["name"], best["crfid"], best["name"], stars_label(best["stars"]), float(best["crf_pct"]),
                             float(best["cmf"]), best["crash_type"], best["severity"], best["control"] or "not specified",
                             note))
    return out, rejected


def site_check(candidate: Candidate, movement: str, right_turn_signalised: bool) -> tuple[bool, str]:
    """Rules that depend on the site: a Leading Pedestrian Interval only separates pedestrians from turning
    vehicles that are released by the same signal, so it cannot address uncontrolled right turns."""
    if candidate.psc == "Leading Pedestrian Interval" and movement == "right" and not right_turn_signalised:
        return False, "LPI rejected: right turns are not signal-controlled at this site"
    return True, ""


def turn_movement(track: pd.DataFrame, min_speed: float = 1.0) -> str:
    """left / right / through / u_turn from the net change in travel direction (x east, y north)."""
    moving = track[np.hypot(track["vx"], track["vy"]) > min_speed]
    if len(moving) < 6:
        return "unknown"
    k = max(2, len(moving) // 5)
    h0 = np.arctan2(moving["vy"].iloc[:k].mean(), moving["vx"].iloc[:k].mean())
    h1 = np.arctan2(moving["vy"].iloc[-k:].mean(), moving["vx"].iloc[-k:].mean())
    d = np.degrees((h1 - h0 + np.pi) % (2 * np.pi) - np.pi)
    if abs(d) < 35:
        return "through"
    if abs(d) > 150:
        return "u_turn"
    return "left" if d > 0 else "right"
