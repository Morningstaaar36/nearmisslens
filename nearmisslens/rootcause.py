"""What a junction's crashes have in common, from the police records the brief already reads.

Patterns: who was hurt (pedestrian, cyclist, only people in vehicles), police-recorded contributing factors, vehicle
types, time of day, darkness and wet roads, crash types, the street of the first vehicle. Which of them a city records
is in its crash adapter (registry.json: factor_fields, time_field, vehicle_fields with vehicle_groups, street_fields,
light_fields, surface_fields, crash_type_fields); a field a city lacks is listed as not recorded.

The gate: a pattern is called over-represented only if the junction has at least MIN_CRASHES crashes and a one-sided
binomial test against the city baseline (the same patterns pooled over the city's screened priority junctions) stays
below 0.05 after a Holm correction across every pattern tested. Police factors describe what an officer wrote down,
not a proven cause, and the wording says so."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from scipy.stats import binomtest

from . import opendata
from .config import since

ALPHA = 0.05  # the family-wise error rate the Holm correction holds, as in the miner (validation/experiments/T15.json)
from .evaluate import RESULTS_DIR

MIN_CRASHES = 10
EMPTY = {"", "unspecified", "unknown", "does not apply", "n/a", "na", "none", "other", "not applicable", "nan"}
UNKNOWN = re.compile(r"\b(unknown|not stated|unspecified|not reported|not recorded)\b", re.I)


def _empty(v: str) -> bool:
    """A value that records nothing: blank, 'unknown', or a category that is itself 'unknown / not stated' (a crash
    type 'bicycle-unknown/not stated' says the type was not recorded; it is not something crashes have in common)."""
    return v.lower() in EMPTY or bool(UNKNOWN.search(v))


def _num(r: dict, fields: list[str]) -> float:
    return sum(opendata._num(r.get(f)) for f in fields or [])


def _hour(v) -> int | None:
    s = str(v or "").strip()
    m = re.match(r"(\d{1,2})(?::\d{2})?", s)
    return int(m.group(1)) % 24 if m else None


def tags(r: dict, a: dict) -> tuple[set[str], set[str]]:
    """The patterns one crash shows, and the kinds of pattern its adapter cannot record."""
    out, missing = set(), set()
    inj, kil = a.get("injured", {}), a.get("killed", {})
    ped = _num(r, inj.get("pedestrian", []) + kil.get("pedestrian", []))
    cyc = _num(r, inj.get("cyclist", []) + kil.get("cyclist", []))
    hurt = sum(_num(r, fs) for m in (inj, kil) for fs in m.values())
    if "pedestrian" in inj:
        out |= {"a pedestrian hurt"} if ped else set()
        out |= {"a cyclist hurt"} if cyc else set()
        out |= {"only people in vehicles hurt"} if hurt and not ped and not cyc else set()
    else:
        missing.add("who was hurt, by mode")
    if hurt:
        out.add("someone hurt")
    labels = a.get("labels") or {}
    for f in a.get("factor_fields", []):
        v = str(r.get(f) or "").strip()
        if v.lower() in ("y", "yes", "true", "1"):  # a flag field: its label (or name) is the factor
            out.add(f"factor: {labels.get(f, f.lower())}")
        elif not _empty(v) and not _empty(str(labels.get(v, v))) and v.lower() not in ("n", "no", "false", "0") \
                and _meaningful(v, labels):
            out.add(f"factor: {labels.get(v, v.lower())}")
    if not a.get("factor_fields"):
        missing.add("contributing factors")
    groups = a.get("vehicle_groups") or {}
    if a.get("vehicle_fields"):
        kinds = " ".join(str(r.get(f) or "").lower() for f in a["vehicle_fields"])
        out |= {f"vehicle: {g}" for g, pat in groups.items() if re.search(pat, kinds)}
    else:
        missing.add("vehicle types")
    if a.get("time_field"):
        h = _hour(r.get(a["time_field"]))
        if h is not None:
            out.add("at night (7 pm to 6 am)" if h >= 19 or h < 6 else "in daylight hours")
            if 7 <= h < 10 or 16 <= h < 19:
                out.add("in the rush hours")
    else:
        missing.add("time of day")
    light = " ".join(str(r.get(f) or "").lower() for f in a.get("light_fields", []))
    if a.get("light_fields"):
        out |= {"in darkness"} if "dark" in light else set()
    surface = " ".join(str(r.get(f) or "").lower() for f in a.get("surface_fields", []))
    if a.get("surface_fields"):
        out |= {"on a wet or icy road"} if any(w in surface for w in ("wet", "ice", "snow", "slush")) else set()
    for f in a.get("crash_type_fields", []):
        raw = str(r.get(f) or "").strip()
        v = raw.lower()
        if v and not _empty(raw) and not _empty(str(labels.get(raw, v))) and _meaningful(raw, labels):
            out.add(f"crash type: {labels.get(raw, v)}")
    if not a.get("crash_type_fields"):
        missing.add("crash types")
    return out, missing


def _peers(city: str | None) -> str:
    from .citywide import peers
    return peers(city)


def _meaningful(value: str, labels: dict) -> bool:
    """A bare code ('32') says nothing to a reader unless the adapter labels it."""
    return value in labels or not re.fullmatch(r"[\d.\-]+", value)


def phrase(pattern: str) -> str:
    """A pattern as the end of "N% of crashes here ...": 'had a truck or bus involved', 'happened at night'."""
    kind, _, value = pattern.partition(": ")
    if value and kind == "factor":
        return f"had \u201c{value}\u201d recorded as a contributing factor"
    if value and kind == "vehicle":
        return f"involved a {value}"
    if value and kind == "crash type":
        return f"were recorded as \u201c{value}\u201d crashes"
    if pattern.startswith(("at ", "in ", "on ")):
        return f"happened {pattern}"
    return f"had {pattern}"


def profile(rows: list[dict], a: dict) -> tuple[Counter, set[str], int]:
    counts, missing, unspecified = Counter(), set(), 0
    for r in rows:
        t, m = tags(r, a)
        counts.update(t)
        missing |= m
        if a.get("factor_fields") and not any(x.startswith("factor: ") for x in t):
            unspecified += 1
    return counts, missing, unspecified


def baseline(city: str, a: dict, years: int = 5, radius_m: float = 100) -> dict | None:
    """The same patterns pooled over the city's screened priority junctions (each crash once), cached on disk."""
    from . import citywide
    path = RESULTS_DIR / "bench" / f"baseline_{city}_{since(years).isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text())
    screens = dict(citywide.screened())
    if city not in screens:
        return None
    seen, rows = set(), []
    for j in screens[city]["rows"]:
        for r in opendata.rows_near(a, j["lat"], j["lon"], radius_m, since(years)):
            key = r.get(a.get("id_field") or "") or json.dumps(r, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                rows.append(r)
    counts, _, _ = profile(rows, a)
    out = {"city": city, "since": since(years).isoformat(), "crashes": len(rows), "counts": dict(counts)}
    path.write_text(json.dumps(out, indent=0))
    return out


def analyse(lat: float, lon: float, years: int = 5, radius_m: float = 100) -> dict:
    """The junction's crash patterns, each with its share, the city baseline and whether it is over-represented."""
    found = opendata.adapters_for(lat, lon, "crash")
    if not found:
        return {"error": "no crash dataset is registered for this place"}
    a = found[0]
    rows = opendata.rows_near(a, lat, lon, radius_m, since(years))
    n = len(rows)
    counts, missing, unspecified = profile(rows, a)
    base = baseline(a.get("city") or "", a, years, radius_m)
    tested = []
    for name, k in counts.most_common():
        if name == "someone hurt":
            continue
        share = k / n if n else 0.0
        p0 = (base["counts"].get(name, 0) / base["crashes"]) if base and base["crashes"] else None
        p = binomtest(k, n, p0, alternative="greater").pvalue if p0 and 0 < p0 < 1 and n >= MIN_CRASHES else None
        tested.append({"pattern": name, "phrase": phrase(name), "crashes": k, "share": round(share, 3),
                       "city_share": round(p0, 3) if p0 is not None else None, "p": p})
    # Holm: the i-th smallest p-value must be below ALPHA / (m - i); stop at the first that is not
    ps = sorted((t for t in tested if t["p"] is not None), key=lambda t: t["p"])
    m, holding = len(ps), True
    for i, t in enumerate(ps):
        holding = holding and bool(t["p"] < ALPHA / (m - i))
        t["over_represented"] = holding  # a plain bool: numpy's would be saved as the string "False"
    for t in tested:
        t.setdefault("over_represented", False)
        t["p"] = round(float(t["p"]), 5) if t["p"] is not None else None
    over = [t for t in tested if t["over_represented"]]
    return {"crashes": n, "since": since(years).isoformat(), "radius_m": radius_m, "source": a["source"],
            "baseline": {"crashes": base["crashes"], "junctions": _peers(a.get("city"))} if base else None,
            "patterns": tested[:25], "over_represented": over,
            "factor_unspecified_share": round(unspecified / n, 3) if n and a.get("factor_fields") else None,
            "not_recorded": sorted(missing), "enough_crashes": n >= MIN_CRASHES,
            "wording": "what police records show these crashes have in common; recorded factors are an officer's "
                       "account, not a proven cause"}
