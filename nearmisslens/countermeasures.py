from __future__ import annotations

import functools
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


ALLOWED_PATH = Path(__file__).resolve().parent / "data" / "cmf_allow.csv"  # the curated records, shipped with the code
POP_CONDITION = {"night": "nighttime", "wet": "wet or low-friction pavement",  # populations that are conditions
                 "walking_along": "pedestrians walking along the roadway"}
POPULATIONS = {  # crash populations a CMF record can cover, as the brief names them
    "pedestrian": "pedestrian injury crashes", "all": "injury crashes", "rear_end": "rear-end crashes",
    "angle": "angle crashes", "wet": "injury crashes on wet roads", "night": "injury crashes in darkness",
    "walking_along": "crashes with pedestrians walking along the road"}


@functools.lru_cache(maxsize=4)
def _load(path: str) -> pd.DataFrame:
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


def load_cmf(path: Path = CMF_PATH) -> pd.DataFrame:
    """The CMF Clearinghouse file (nml fetch), or the curated subset shipped with the code when it is absent."""
    return _load(str(path if Path(path).exists() else ALLOWED_PATH)).copy()


def export_allowed(path: Path = CMF_PATH, out: Path = ALLOWED_PATH) -> int:
    """Write the curated records (every cmf_allow id) from the full Clearinghouse file to the shipped subset."""
    ids = {e["crfid"] for i in psc_items() for e in i.get("cmf_allow", [])}
    raw = pd.read_csv(path, encoding="latin-1", dtype=str, keep_default_na=False)
    raw[raw["crfid"].isin(ids)].to_csv(out, index=False, encoding="latin-1")
    return int(raw["crfid"].isin(ids).sum())


def select(item: dict, control: str, populations: dict, cmf: pd.DataFrame,
           site_kinds: frozenset[str] = frozenset()) -> dict:
    """The CMF estimate for one countermeasure at one site, from its curated records only. A record is eligible if
    it is for this site's control (an 'uncontrolled' record never serves a signal), has at least 3 stars, the crash
    record shows the population it covers (wet-road, darkness and walking-along records need those shares), and a
    record studied only at one kind of site ("only_for", e.g. school crossings) is used only where the site is known
    to be that kind. The pick is the record FHWA's fact sheet cites, else the median of the eligible ones (with an even
    count, the middle record with the smaller effect); never the largest effect. A precondition of the chosen record's study sites that the public data cannot show
    ("site_condition", e.g. a change interval below ITE practice) is returned, so the fix is marked for a check."""
    allow = item.get("cmf_allow") or []
    if not allow:
        return {"quantified": False, "reason": item.get("no_cmf_reason", "no CMF Clearinghouse record fits")}
    rows = cmf.drop_duplicates("crfid").set_index("crfid")
    eligible, why = [], []
    for e in allow:
        if e["crfid"] not in rows.index:
            why.append(f"CMF {e['crfid']} is not in the Clearinghouse file")
            continue
        if e.get("only_for") and e["only_for"] not in site_kinds:
            why.append(f"CMF {e['crfid']} was measured only at {e['only_for']}, and this site is not known to be one")
            continue
        r = rows.loc[e["crfid"]]
        if "any" not in e["control"] and control not in e["control"]:
            why.append(f"its CMF Clearinghouse records are for {' or '.join(e['control']).lower()} sites"
                       + (f", and this site's control is {control.lower()}" if control != "unknown" else
                          ", and this site's control is not known"))
            continue
        if not (r["stars"] >= 3):
            why.append(f"CMF {e['crfid']} is rated below 3 stars")
            continue
        n = populations.get(e["population"])
        if n is None:
            why.append(f"the crash record does not show {POPULATIONS[e['population']]}")
            continue
        if n <= 0:
            why.append(f"the record has no {POPULATIONS[e['population']]}")
            continue
        eligible.append((e, r))
    if not eligible:
        return {"quantified": False, "reason": "; ".join(dict.fromkeys(why))}
    cited = [x for x in eligible if x[0].get("fhwa_cited")]
    pops = [x[0]["population"] for x in eligible]
    pop = cited[0][0]["population"] if cited else ("all" if "all" in pops else pops[0])
    same = sorted((x for x in eligible if x[0]["population"] == pop), key=lambda x: float(x[1]["cmf"]))
    if cited:
        e, r = cited[0]
        how = "the record FHWA's fact sheet cites"
    else:
        e, r = same[len(same) // 2]  # sorted by CMF: with an even count, the upper middle (the smaller effect)
        how = ("the only eligible record" if len(same) == 1 else f"the median of {len(same)} eligible records"
               if len(same) % 2 else f"the more conservative of the two middle records of {len(same)}")
    cmfs = [float(x[1]["cmf"]) for x in same]
    return {"quantified": True, "cmf_id": e["crfid"], "cmf": round(float(r["cmf"]), 3), "stars": stars_label(r["stars"]),
            "cmf_name": r["name"], "cmf_crash_type": r["crash_type"], "cmf_severity": r["severity"],
            "population": pop, "targets": POPULATIONS[pop], "target_crashes_5y": populations[pop],
            "chosen_by": how, "fhwa_cited": bool(e.get("fhwa_cited")), "site_condition": e.get("site_condition"),
            "cmf_range": [round(min(cmfs), 3), round(max(cmfs), 3)]}


def stars_label(stars: float) -> str:
    return f"{int(stars)}★" if stars == stars and stars >= 1 else "not rated"


@functools.lru_cache(maxsize=1)
def _psc() -> str:
    return resources.files("nearmisslens").joinpath("data/fhwa_psc.json").read_text()


def psc_items() -> list[dict]:
    return json.loads(_psc())["items"]


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
    for item in psc_items():
        if not item.get("cmf_allow"):
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
        allowed = {e["crfid"]: e for e in item["cmf_allow"]
                   if (not control or "any" in e["control"] or control in e["control"])
                   and (e["population"] not in POP_CONDITION or POP_CONDITION[e["population"]] in conditions)}
        if not allowed:
            need = {POP_CONDITION[e["population"]] for e in item["cmf_allow"] if e["population"] in POP_CONDITION}
            rejected.append({"psc": item["name"], "reason": f"requires {' or '.join(sorted(need))}, which the observed "
                                                            "conflicts do not show" if need else
                             f"its CMF records are for other site controls than {control}"})
            continue
        rows = cmf[cmf["crfid"].isin(allowed)]  # the curated records only
        if rows.empty:
            continue
        # a record for all crash types covers this conflict's type too
        typed = rows[rows["crash_type"].apply(lambda c: c == "All" or any(t in c.split(",") or t == c for t in types))]
        if typed.empty:
            rejected.append({"psc": item["name"], "reason": f"no CMF for crash type {types}"})
            continue
        worse = typed[typed["cmf"] >= 1]
        for r in worse.itertuples():
            rejected.append({"psc": item["name"], "crfid": r.crfid, "reason": f"CMF {r.cmf:.3f} >= 1 (no reduction) for {r.crash_type}"})
        for r in typed[typed["cmf"] <= 0].itertuples():
            rejected.append({"psc": item["name"], "crfid": r.crfid, "reason": f"CMF {r.cmf:.3f} is not a plausible estimate"})
        reducing = typed[(typed["cmf"] > 0) & (typed["cmf"] < 1)]
        good = reducing[reducing["stars"] >= min_stars]
        if good.empty:
            rejected.append({"psc": item["name"], "reason": f"no reducing CMF rated >= {min_stars} stars"})
            continue
        # the record FHWA's fact sheet cites, else the median, never the largest effect
        cited = good[good["crfid"].map(lambda c: allowed[c].get("fhwa_cited", False))]
        ordered = good.sort_values("cmf")
        best = cited.iloc[0] if not cited.empty else ordered.iloc[(len(ordered) - 1) // 2]
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
