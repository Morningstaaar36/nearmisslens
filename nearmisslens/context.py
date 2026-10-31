"""Context agent: what the official record says about a junction. Free open-data APIs give the street layout
(OpenStreetMap), the police-reported crash history and the city's safety plans (High Injury Network or Vision Zero
priority lists, street improvement projects) near a point. Code turns them into a dossier of counts; Muse Spark writes
a short memo for a city engineer, and a checker inside its finish tool rejects any number that is not in the dossier.

Crash and plan data come from the open-data registry (opendata.py): adapters seeded by hand for New York, Washington
DC, Chicago and Los Angeles, and adapters the data agent (datascout.py) finds and validates for other cities. Where no
adapter exists only OpenStreetMap is used, and the dossier says so."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from . import panel
from .agent import Tool, run_agent
from .config import SETTINGS
from .meta_client import MetaClient

UA = {"User-Agent": "NearMissLens/0.2 (road-safety research; https://github.com/Morningstaaar36/nearmisslens)"}
OVERPASS = "https://overpass-api.de/api/interpreter"
CRASH_RADIUS_M, PLAN_RADIUS_M, OSM_RADIUS_M = 100, 150, 80
TREATMENT_RADIUS_M = 60
YEARS = 5
GAP_MIN_INJURY_CRASHES = 10


def city_of(lat: float, lon: float) -> str | None:
    """The registry city whose bounding box holds the point (registry.json "cities")."""
    from . import opendata
    return next((c["id"] for c in opendata.load_cities()
                 if c["bbox"][0] <= lat <= c["bbox"][2] and c["bbox"][1] <= lon <= c["bbox"][3]), None)


def _cache_dir() -> Path:
    p = Path(SETTINGS.cache_dir) / "context"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fetch(url: str, params: dict | None = None, data: dict | None = None, timeout: float = 90.0) -> tuple[dict, float]:
    """GET (or POST form) JSON with a disk cache keyed by the request; returns (json, seconds, 0 when cached)."""
    key = hashlib.sha256(json.dumps([url, params, data], sort_keys=True).encode()).hexdigest()[:24]
    path = _cache_dir() / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text()), 0.0
    if SETTINGS.replay:
        raise FileNotFoundError(f"context request not cached: {url}")
    t = time.time()
    for attempt in range(3):
        try:
            with httpx.Client(headers=UA, timeout=timeout, follow_redirects=True) as c:
                r = c.post(url, data=data) if data is not None else c.get(url, params=params)
            if r.status_code == 200:
                out = r.json()
                path.write_text(json.dumps(out))
                return out, round(time.time() - t, 2)
            err = f"HTTP {r.status_code}"
        except (httpx.TransportError, json.JSONDecodeError) as e:
            err = f"{type(e).__name__}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {err}")


def osm(lat: float, lon: float) -> dict:
    q = (f"[out:json][timeout:60];("
         f"node(around:{OSM_RADIUS_M},{lat},{lon})[highway~\"traffic_signals|crossing|stop|give_way\"];"
         f"way(around:{OSM_RADIUS_M},{lat},{lon})[highway~\"primary|secondary|tertiary|residential|trunk|unclassified\"];"
         f"node(around:400,{lat},{lon})[amenity~\"school|kindergarten\"];"
         f"node(around:200,{lat},{lon})[highway=bus_stop];);out tags center;")
    js, secs = fetch(OVERPASS, data={"data": q}, timeout=120)
    el = js.get("elements", [])
    nodes = [e.get("tags", {}) for e in el if e["type"] == "node"]
    ways = [e.get("tags", {}) for e in el if e["type"] == "way"]
    roads = {}
    for w in ways:
        name = w.get("name") or w.get("ref") or "unnamed"
        r = roads.setdefault(name, {"highway": w.get("highway"), "lanes": set(), "maxspeed": set()})
        if w.get("lanes"):
            r["lanes"].add(w["lanes"])
        if w.get("maxspeed"):
            r["maxspeed"].add(w["maxspeed"])
    return {"seconds": secs, "signals": sum(n.get("highway") == "traffic_signals" for n in nodes),
            "crossings": sum(n.get("highway") == "crossing" for n in nodes),
            "marked_crossings": sum(n.get("highway") == "crossing" and n.get("crossing") in
                                    ("marked", "traffic_signals", "zebra", "uncontrolled") for n in nodes),
            "stop_signs": sum(n.get("highway") in ("stop", "give_way") for n in nodes),
            "schools_400m": sum(n.get("amenity") in ("school", "kindergarten") for n in nodes),
            "bus_stops_200m": sum(n.get("highway") == "bus_stop" for n in nodes),
            "roads": [{"name": k, "highway": v["highway"], "lanes": sorted(v["lanes"]), "maxspeed": sorted(v["maxspeed"])}
                      for k, v in sorted(roads.items())]}


def _since(years: int = YEARS) -> dt.date:
    return dt.date.today().replace(year=dt.date.today().year - years)


def registry_crashes(lat: float, lon: float) -> dict | None:
    """The crash profile from the first registry adapter covering the point (seeded or found by the data agent)."""
    from . import opendata
    found = opendata.adapters_for(lat, lon, "crash")
    return opendata.crash_summary(found[0], lat, lon, CRASH_RADIUS_M, YEARS) if found else None


def registry_plans(lat: float, lon: float) -> dict | None:
    """City designations and recorded safety projects or treatments near the point, from the registry."""
    from . import opendata
    des = opendata.adapters_for(lat, lon, "designation")
    pro = opendata.adapters_for(lat, lon, "project")
    if not des and not pro:
        return None
    designated = []
    for a in des:
        designated += [{"designation": a.get("label", a["id"]), "name": n} for n in opendata.designated_near(a, lat, lon)]
    projects = []
    for a in pro:
        projects += opendata.projects_near(a, lat, lon)
    return {"source": "; ".join(sorted({a["source"] for a in des + pro})), "designations": designated,
            "designated": bool(designated), "projects": projects}


def dossier(lat: float, lon: float, street: bool = True) -> dict:
    """Everything the open record says about the junction, as counts with their sources. street=False skips
    OpenStreetMap (slow), for citywide screens. Crash and plan data come from the open-data registry, so any city
    with an adapter works; without one the dossier says so."""
    city = city_of(lat, lon)
    out = {"lat": round(lat, 6), "lon": round(lon, 6), "city": city, "years": YEARS}
    sources = (("street", lambda: osm(lat, lon)),) if street else ()
    for name, fn in sources + (("crashes", lambda: registry_crashes(lat, lon)), ("plans", lambda: registry_plans(lat, lon))):
        try:
            out[name] = fn()
        except Exception as e:  # an unavailable source is reported, not fatal
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    cr, pl = out.get("crashes") or {}, out.get("plans") or {}
    recent = [p for p in pl.get("projects", []) if isinstance(p.get("year"), int) and p["year"] >= _since().year]
    out["plan_gap"] = bool(cr.get("injury_crashes", 0) >= GAP_MIN_INJURY_CRASHES and not recent) if cr and pl else None
    out["recent_projects"] = len(recent)
    if not cr:
        out["crashes"] = {"error": "no open crash dataset is registered for this place; run the data agent "
                                   "(nml discover LAT LON)"}
    return out


MODEL = "muse-spark-1.3-contributor"
INSTRUCTIONS = (
    "You write for a city traffic engineer. From the junction dossier only, write a memo of at most 120 words: what "
    "the street layout is, what the police-reported crash record shows over the period (who was hurt, the main "
    "factors), whether the city has designated this location (High Injury Network or Vision Zero priority) and what "
    "projects it has done, and whether there is a plan gap (plan_gap true means at least "
    f"{GAP_MIN_INJURY_CRASHES} injury crashes and no project in the period). Use only numbers in the dossier, and say "
    "when a source is missing. Call finish with the memo; if it is rejected, fix the errors.")


# a number written next to one of these words must be the record's value for it (the field names it maps to)
LABELS = [  # (name, words before the number, words after it, field-name pattern)
    ("crashes avoided", r"\b(prevent|prevents|avoid|avoids|avoided|cut|cuts|save|saves)\b[^.;]{0,25}$", None,
     r"avoided"),
    ("deaths", None, r"^[^.;\d]{0,30}\b(killed|deaths?|died|dead|fatal|fatalities)\b", r"killed|death|fatal"),
    ("pedestrians injured", None, r"^\s*pedestrians?\b[^.;\d]{0,20}\b(injured|hurt)\b", r"pedestrian.*injur"),
    ("cyclists injured", None, r"^\s*(cyclists?|bicyclists?)\b[^.;\d]{0,20}\b(injured|hurt)\b", r"cyclist.*injur"),
    ("injury crashes", None, r"^\s*(\w+\s){0,2}(injury crashes|crashes with injur)", r"injury_crash"),
    ("dollars", r"\$\s*$", None, r"usd|harm|cost|dollar|million"),
]


def _labelled(facts) -> dict[str, list[float]]:
    """Every numeric value in the facts by the name of the field holding it."""
    out: dict[str, list[float]] = {}

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, str(k))
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            out.setdefault(key.lower(), []).append(float(o))
    walk(facts)
    return out


class FactCheck:
    """Numbers a memo may use: those in the dossier. A number written next to a label (deaths, pedestrians injured,
    injury crashes, crashes avoided, dollars) must also be the record's value for that label, so "29 pedestrians were
    killed" is refused where the record has 29 pedestrians injured and no deaths."""

    def __init__(self, facts: dict):
        # numbers in values and in field names (schools_400m, by_year keys such as 2022) are both in the dossier
        self.known = set(panel.numbers_in(facts)) | {panel._value(t) for t in panel.NUMBER.findall(
            json.dumps(facts, default=str))}
        fields = _labelled(facts)
        self.by_label = {}
        for name, before, after, pattern in LABELS:
            vals = [v for k, vs in fields.items() if re.search(pattern, k) for v in vs]
            if name == "dollars":  # "$8.8 million" and "$561,000" both name a dollar field
                vals += [v / 1e6 for v in vals] + [v / 1e3 for v in vals]
            self.by_label[name] = vals or [0.0]  # an absent count is zero (the record lists only non-zero counts)
        self.known |= {round(v, 1) for v in self.by_label["dollars"]} | {0.0}  # "$8.8 million"; absent counts are 0

    def text(self, text: str) -> list[str]:
        a, b = self._text(text), self._text(panel.normalise_decimals(text))
        return a if len(a) <= len(b) else b

    def _text(self, text: str) -> list[str]:
        bad = []
        for m in panel.NUMBER.finditer(text):
            t = m.group(0)
            v, tol = panel._value(t), 0.5 * 10 ** -panel._decimals(t) + 1e-9
            if not any(abs(k - v) <= tol for k in self.known):
                bad.append(f"number {t} is not in the dossier")
                continue
            tail = text[m.end():m.end() + 45]
            if tail.lstrip().startswith("%") or (len(t) == 4 and t[:2] in ("19", "20")):
                continue  # percentages and years carry no label
            head = text[max(0, m.start() - 30):m.start()]
            for name, before, after, _ in LABELS:
                if (before and re.search(before, head, re.I)) or (after and re.search(after, tail, re.I)):
                    if not any(abs(k - v) <= tol for k in self.by_label[name]):
                        bad.append(f"{t} is not the record's number of {name}")
                    break
        return list(dict.fromkeys(bad))


def memo(client: MetaClient, d: dict, tag: str, checked: bool = True) -> dict:
    """Spark's memo on a dossier. checked=False is the ablation (finish accepts anything; errors only recorded)."""
    check = FactCheck(d)
    attempts = []

    def finish(memo: str) -> dict:
        errors = check.text(memo)
        attempts.append({"memo": memo, "errors": errors})
        return {"error": "rejected by the fact checker", "errors": errors} if errors and checked else {"ok": True}

    tool = Tool("finish", "Submit the memo.", panel._obj({"memo": {"type": "string"}}, ["memo"]), finish)
    run = run_agent(client, MODEL, INSTRUCTIONS, "Dossier:\n" + json.dumps(d, default=str), [tool], 6, 0.02,
                    effort="low", tag=tag, escalate_after=3)
    final = next((a for a in reversed(attempts) if not a["errors"]), attempts[-1] if attempts else None)
    if not checked and attempts:
        final = attempts[-1]
    return {"memo": final["memo"] if final else "", "errors": final["errors"] if final else ["no memo"],
            "attempts": len(attempts), "stopped": run.stopped, "usd": round(run.usd, 5), "turns": run.turns}
