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
import math
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from . import panel
from .agent import Tool, run_agent
from .cache import atomic_write
from .config import SETTINGS
from .meta_client import MetaClient
from .config import MODELS

UA = {"User-Agent": "NearMissLens/0.2 (road-safety research; https://github.com/Morningstaaar36/nearmisslens)"}
OVERPASS = "https://overpass-api.de/api/interpreter"
# public Overpass mirrors: a request to OVERPASS falls back to these when the main server refuses or is busy; the cache
# key stays the main URL, so a cached answer is the same whichever server gave it
OVERPASS_MIRRORS = ("https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
CRASH_RADIUS_M, PLAN_RADIUS_M, OSM_RADIUS_M = 100, 150, 80
TREATMENT_RADIUS_M = 60
YEARS = 5
GAP_MIN_INJURY_CRASHES = 10


def deaths(cr: dict) -> int:
    """People killed in a crash summary: the deaths by mode where the city records the mode, else the dataset's total
    (some cities record deaths without the mode; leaving that total out once made letters say no one was killed)."""
    by_mode = sum(int(cr.get(k) or 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed"))
    return by_mode or int(cr.get("any_killed") or 0)


def city_of(lat: float, lon: float) -> str | None:
    """The registry city whose bounding box holds the point (registry.json "cities")."""
    from . import opendata
    return next((c["id"] for c in opendata.load_cities()
                 if c["bbox"][0] <= lat <= c["bbox"][2] and c["bbox"][1] <= lon <= c["bbox"][3]), None)


def _cache_dir() -> Path:
    p = Path(SETTINGS.cache_dir) / "context"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(url: str, params: dict | None, data: dict | None, timeout: float, total: float | None = None) -> tuple[int, bytes]:
    """(status, body) of one GET (or form POST), within `total` seconds in all (default `timeout`): httpx's timeout
    counts each read, so a server that trickles its answer could otherwise hold a request for many minutes. Overpass
    gets its own timeout as the total (a mirror answers instead); a city's data download gets four times it."""
    total = timeout if total is None else total
    end = time.time() + total
    with httpx.Client(headers=UA, timeout=timeout, follow_redirects=True) as c:
        with c.stream("POST" if data is not None else "GET", url, data=data, params=params) as r:
            body = bytearray()
            for chunk in r.iter_bytes():
                body += chunk
                if time.time() > end:
                    raise httpx.ReadTimeout(f"no complete answer in {total:.0f} s")
            return r.status_code, bytes(body)


def fetch(url: str, params: dict | None = None, data: dict | None = None, timeout: float = 90.0,
          attempts: int = 6) -> tuple[dict, float]:
    """GET (or POST form) JSON with a disk cache keyed by the request; returns (json, seconds, 0 when cached)."""
    key = hashlib.sha256(json.dumps([url, params, data], sort_keys=True).encode()).hexdigest()[:24]
    path = _cache_dir() / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text()), 0.0
    if SETTINGS.replay:
        raise FileNotFoundError(f"context request not cached: {url}")
    t = time.time()
    servers = [url, *OVERPASS_MIRRORS] if url == OVERPASS else [url]
    for attempt in range(attempts):
        target = servers[attempt % len(servers)]
        try:
            status, body = _get(target, params, data, timeout, total=timeout if url == OVERPASS else 4 * timeout)
            if status == 200:
                out = json.loads(body)
                atomic_write(path, json.dumps(out))
                return out, round(time.time() - t, 2)
            err = f"HTTP {status}"
            if status < 500 and status != 429:  # a bad request will not get better by waiting
                break
        except (httpx.TransportError, json.JSONDecodeError) as e:
            err = f"{type(e).__name__}"
        if attempt + 1 < attempts and attempt + 1 >= len(servers):  # back off only before asking a server again:
            time.sleep(min(60, 3 * 2 ** attempt))  # public servers shed load with 429/503 (a mirror is tried at once)
    raise RuntimeError(f"{url}: {err}")


OSM_API = "https://api.openstreetmap.org/api/0.6"
_OVERPASS_DOWN: list[str] = []  # set after Overpass fails once, so later requests go straight to the OSM API


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.pi / 180
    return 6371000 * math.hypot((lon2 - lon1) * k * math.cos((lat1 + lat2) / 2 * k), (lat2 - lat1) * k)


def osm_map(lat: float, lon: float, radius_m: float) -> list[dict]:
    """Every element in a box of radius_m around the point, from the OpenStreetMap API's map call: nodes with their
    coordinates and tags, and the ways crossing the box with their tags. The fallback when Overpass is unreachable."""
    dlat = radius_m * 1.1 / 111320
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    js, _ = fetch(f"{OSM_API}/map.json", {"bbox": f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"},
                  timeout=90)
    return js.get("elements", [])


def _down_file() -> Path:
    return _cache_dir() / "overpass_down.txt"


def overpass(query: str, timeout: float = 120) -> dict:
    """An Overpass query, unless Overpass failed in the last hour (then RuntimeError at once, so callers fall back
    without waiting through the retries again). A cached answer is always served."""
    key = hashlib.sha256(json.dumps([OVERPASS, None, {"data": query}], sort_keys=True).encode()).hexdigest()[:24]
    if not (_cache_dir() / f"{key}.json").exists():
        f = _down_file()
        if not _OVERPASS_DOWN and f.exists() and time.time() - f.stat().st_mtime < 3600:
            _OVERPASS_DOWN.append(f.read_text()[:120])
        if _OVERPASS_DOWN:
            raise RuntimeError(f"Overpass unreachable earlier: {_OVERPASS_DOWN[0]}")
    try:
        return fetch(OVERPASS, data={"data": query}, timeout=min(timeout, 60), attempts=3)  # each server once: callers
    except RuntimeError as e:                                                                # have a fallback
        _OVERPASS_DOWN.append(str(e)[:120])
        if not SETTINGS.replay:
            _down_file().write_text(str(e)[:120])
        raise


def _osm_from_map(lat: float, lon: float) -> tuple[list[dict], list[dict], float]:
    """The same nodes and ways as osm()'s Overpass query, from two OSM API map calls."""
    t = time.time()
    near = osm_map(lat, lon, 200)
    roads = ("primary", "secondary", "tertiary", "residential", "trunk", "unclassified")
    nodes = [e.get("tags", {}) for e in near if e.get("type") == "node" and e.get("tags") and (
        (e["tags"].get("highway") in ("traffic_signals", "crossing", "stop", "give_way")
         and metres(lat, lon, e["lat"], e["lon"]) <= OSM_RADIUS_M) or e["tags"].get("highway") == "bus_stop")]
    keep = {e["id"] for e in near if e.get("type") == "node" and metres(lat, lon, e["lat"], e["lon"]) <= OSM_RADIUS_M}
    ways = [e.get("tags", {}) for e in near if e.get("type") == "way" and e.get("tags", {}).get("highway") in roads
            and keep & set(e.get("nodes", []))]
    try:  # a 400 m box in a dense centre can pass the API's node limit; then schools are not counted
        nodes += [e["tags"] for e in osm_map(lat, lon, 400) if e.get("type") == "node" and e.get("tags", {}).get(
            "amenity") in ("school", "kindergarten") and metres(lat, lon, e["lat"], e["lon"]) <= 400]
    except RuntimeError:
        nodes.append({"_schools_unknown": "yes"})
    return nodes, ways, round(time.time() - t, 2)


JUNCTION_SIGNAL_M = 45  # a signal this close is the junction's own; one 70-100 m off belongs to the next crossing


def signals_at_junction(lat: float, lon: float) -> int | None:
    """Traffic signals mapped within JUNCTION_SIGNAL_M of the junction, or None when it cannot be asked (a replay
    without this request cached, or the map servers down): then the 80 m count stands, as before."""
    q = f"[out:json][timeout:25];node(around:{JUNCTION_SIGNAL_M},{lat},{lon})[highway=traffic_signals];out ids;"
    try:
        js, _ = overpass(q, timeout=25)
        return len(js.get("elements", []))
    except (RuntimeError, FileNotFoundError):
        pass
    try:  # the OSM API's map of the junction (cached for the street layout already), with each node's position
        return sum(1 for e in osm_map(lat, lon, 200) if e.get("type") == "node"
                   and (e.get("tags") or {}).get("highway") == "traffic_signals"
                   and metres(lat, lon, e["lat"], e["lon"]) <= JUNCTION_SIGNAL_M)
    except (RuntimeError, FileNotFoundError):
        return None


def osm(lat: float, lon: float) -> dict:
    q = (f"[out:json][timeout:60];("
         f"node(around:{OSM_RADIUS_M},{lat},{lon})[highway~\"traffic_signals|crossing|stop|give_way\"];"
         f"way(around:{OSM_RADIUS_M},{lat},{lon})[highway~\"primary|secondary|tertiary|residential|trunk|unclassified\"];"
         f"node(around:400,{lat},{lon})[amenity~\"school|kindergarten\"];"
         f"node(around:200,{lat},{lon})[highway=bus_stop];);out tags center;")
    try:
        js, secs = overpass(q, timeout=30)  # a small box: a healthy server answers in seconds
        el = js.get("elements", [])
        nodes = [e.get("tags", {}) for e in el if e["type"] == "node"]
        ways = [e.get("tags", {}) for e in el if e["type"] == "way"]
    except (RuntimeError, FileNotFoundError):  # Overpass down, or (replay) not cached: the OSM API's cached map
        nodes, ways, secs = _osm_from_map(lat, lon)
    roads = {}
    for w in ways:
        name = w.get("name") or w.get("ref") or "unnamed"
        r = roads.setdefault(name, {"highway": w.get("highway"), "lanes": set(), "maxspeed": set(), "ref": set(),
                                    "operator": set()})
        for k in ("ref", "operator"):  # route numbers and operators say who may own the road
            if w.get(k):
                r[k].add(w[k])
        if w.get("lanes"):
            r["lanes"].add(w["lanes"])
        if w.get("maxspeed"):
            r["maxspeed"].add(w["maxspeed"])
    signals = sum(n.get("highway") == "traffic_signals" for n in nodes)
    return {"seconds": secs, "signals": signals, "signals_at_junction": signals_at_junction(lat, lon) if signals else 0,
            "crossings": sum(n.get("highway") == "crossing" for n in nodes),
            "marked_crossings": sum(n.get("highway") == "crossing" and n.get("crossing") in
                                    ("marked", "traffic_signals", "zebra", "uncontrolled") for n in nodes),
            "stop_signs": sum(n.get("highway") in ("stop", "give_way") for n in nodes),
            "schools_400m": None if any("_schools_unknown" in n for n in nodes) else
            sum(n.get("amenity") in ("school", "kindergarten") for n in nodes),
            "bus_stops_200m": sum(n.get("highway") == "bus_stop" for n in nodes),
            "roads": [{"name": k, "highway": v["highway"], "lanes": sorted(v["lanes"]), "maxspeed": sorted(v["maxspeed"]),
                       "ref": sorted(v["ref"]), "operator": sorted(v["operator"])} for k, v in sorted(roads.items())]}


def _since(years: int = YEARS) -> dt.date:
    from .config import since
    return since(years)


def registry_crashes(lat: float, lon: float, corner: str | None = None) -> dict | None:
    """The crash profile from the first registry adapter covering the point (seeded or found by the data agent); with
    the corner's name, only the crashes the dataset does not place at another intersection or street."""
    from . import opendata
    found = opendata.adapters_for(lat, lon, "crash")
    return opendata.crash_summary(found[0], lat, lon, CRASH_RADIUS_M, YEARS, corner=corner) if found else None


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


def dossier(lat: float, lon: float, street: bool = True, corner: str | None = None) -> dict:
    """Everything the open record says about the junction, as counts with their sources. street=False skips
    OpenStreetMap (slow), for citywide screens. Crash and plan data come from the open-data registry, so any city
    with an adapter works; without one the dossier says so."""
    city = city_of(lat, lon)
    out = {"lat": round(lat, 6), "lon": round(lon, 6), "city": city, "years": YEARS}
    sources = (("street", lambda: osm(lat, lon)),) if street else ()
    for name, fn in sources + (("crashes", lambda: registry_crashes(lat, lon, corner)), ("plans", lambda: registry_plans(lat, lon))):
        try:
            out[name] = fn()
        except Exception as e:  # an unavailable source is reported, not fatal
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    cr, pl = out.get("crashes") or {}, out.get("plans") or {}
    recent = [p for p in pl.get("projects", []) if isinstance(p.get("year"), int) and p["year"] >= _since().year
              and not p.get("planned")]  # a project dated after the as-of date is planned, not done
    out["plan_gap"] = bool(cr.get("injury_crashes", 0) >= GAP_MIN_INJURY_CRASHES and not recent) if cr and pl else None
    out["recent_projects"] = len(recent)
    if not cr:
        out["crashes"] = {"error": "no open crash dataset is registered for this place; run the data agent "
                                   "(nml discover LAT LON)"}
    return out


MODEL = MODELS["reader"]
INSTRUCTIONS = (
    "You write for a city traffic engineer. From the junction dossier only, write a memo of at most 120 words: what "
    "the street layout is, what the police-reported crash record shows over the period (who was hurt, the main "
    "factors), whether the city has designated this location (High Injury Network or Vision Zero priority) and what "
    "projects it has done, and whether there is a plan gap (plan_gap true means at least "
    f"{GAP_MIN_INJURY_CRASHES} injury crashes and no project in the period). Use only numbers in the dossier, and say "
    "when a source is missing. Call finish with the memo; if it is rejected, fix the errors.")


# a number written next to one of these words must be the record's value for it (the field names it maps to)
LABELS = [  # (name, words before the number, words after it, field-name pattern); the first match decides
    ("dollars", r"\$\s*$", None, r"usd|harm|cost|dollar|million"),
    ("pedestrians killed", None, r"^\s*pedestrians?\b[^.;,\d]{0,20}\b(killed|died|dead)\b", r"pedestrian.*kill"),
    ("cyclists killed", None, r"^\s*(cyclists?|bicyclists?)\b[^.;,\d]{0,20}\b(killed|died|dead)\b", r"cyclist.*kill"),
    ("deaths", None, r"^[^.;,\d]{0,30}\b(killed|deaths?|died|dead|fatal|fatalities)\b", r"killed|death|fatal"),
    ("crashes avoided", r"\b(prevent|prevents|avoid|avoids|avoided|cut|cuts|save|saves)\b[^.;]{0,25}$", None,
     r"avoided"),
    ("pedestrians injured", None, r"^\s*pedestrians?\b[^.;,\d]{0,20}\b(injured|hurt)\b", r"pedestrian.*injur"),
    ("cyclists injured", None, r"^\s*(cyclists?|bicyclists?)\b[^.;,\d]{0,20}\b(injured|hurt)\b", r"cyclist.*injur"),
    ("injury crashes", None, r"^\s*(\w+\s){0,2}(injury crashes|crashes with injur)", r"injury_crash"),
    ("sites", None, r"^\s*(\w+\s)?(sites|intersections|locations)\b", r"(^|_)sites$"),
    ("crashes", None, r"^\s*(\w+\s){0,2}crash(es)?\b", None),  # any count, bound below to its subject and year
]
NAME_KEYS = ("label", "phrase", "countermeasure", "factor", "words", "party", "program", "pattern")  # what a
# sentence can name; a pattern such as "time: night" is also named by its value ("night")
GENERIC = {"crashes", "crash", "street", "streets", "signal", "signals", "pedestrian", "pedestrians", "recorded",
           "vehicle", "vehicles", "people", "injury", "injured", "dedicated", "reduced", "medians", "improve",
           "leading", "contributing", "factor", "other", "night"}
NAIVE = re.compile(r"simple|naive|before/after|before-after|uncontrolled|without a comparison", re.I)
COMPARE = re.compile(r"\b(city|citywide|city-wide|priority|other|across|screened|compared|against|vs|versus)\b", re.I)
BASELINE = re.compile(r"baseline|citywide|^city$|screen", re.I)
PER_YEAR = re.compile(r"\b(a|per|each)\s+year\b|\bannual(ly)?\b|\byearly\b", re.I)
TOTAL = re.compile(r"\bin total\b|\btotal\b|\bfive-year\b|\b5-year\b|\bover (the )?(five|5) years\b", re.I)
# "no", "zero", "never" used as a count; "could be zero" and "no change" are not counts
NEG = re.compile(r"\bnot\b[^.;]{0,25}\bany\b|\b(no|none|never|not a single|not any|without any)\b(?!\s+(measurable\s+|significant\s+|clear\s+)?"
                 r"(change|effect|drop|difference|reduction|evidence|recorded safety))|(?<!be )\bzero\b", re.I)
COUNT_WORDS = re.compile(r"crash|\bsites?\b|evaluat|studied|killed|death|died|injur|hurt", re.I)


def _dates_named(facts, key: str) -> list[str]:
    """Every ISO date held under `key` anywhere in the facts."""
    out = []
    if isinstance(facts, dict):
        for k, v in facts.items():
            if k == key and isinstance(v, str) and re.match(r"(19|20)\d\d-\d\d-\d\d", v):
                out.append(v[:10])
            else:
                out += _dates_named(v, key)
    elif isinstance(facts, list):
        for v in facts:
            out += _dates_named(v, key)
    return out


def _paths(facts) -> list[tuple[tuple, str, float]]:
    """Every numeric value in the facts with its path and the name of the field holding it."""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + (str(k),))
        elif isinstance(o, (list, tuple)):
            for i, v in enumerate(o):
                walk(v, path + (i,))
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            key = next((str(p) for p in reversed(path) if isinstance(p, str)), "")
            out.append((path, key.lower(), float(o)))
    walk(facts, ())
    return out


def _not_recorded(facts) -> set[str]:
    """Labels the record cannot speak to: a mode missing from a "recorded" block (Seattle records injuries only as a
    total), or a count field present as null."""
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            rec = o.get("recorded")
            if isinstance(rec, dict) and isinstance(rec.get("injured_by_mode"), list):
                for mode in ("pedestrian", "cyclist"):
                    if mode not in rec["injured_by_mode"]:
                        out.add(f"{mode}s injured")
            for k, v in o.items():
                if v is None and isinstance(k, str):
                    for name, _b, _a, pattern in LABELS:
                        if pattern and name != "dollars" and re.search(pattern, k.lower()):
                            out.add(name)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(facts)
    return out


def _labelled(facts) -> dict[str, list[float]]:
    """Every numeric value in the facts by the name of the field holding it."""
    out: dict[str, list[float]] = {}
    for _, k, v in _paths(facts):
        out.setdefault(k, []).append(v)
    return out


def _named(facts) -> list[tuple[str, tuple]]:
    """(name, path) of every item the facts name: a program's label, a pattern's phrase, a fix, a factor."""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k in NAME_KEYS:
                v = o.get(k)
                if isinstance(v, str) and len(v.strip(" “”\"")) >= 5:
                    out.append((v.strip(" “”\"").lower(), path))
                    if k == "pattern":  # "time: night", "factor=following too closely AND vehicle=truck"
                        for part in re.split(r"\s+AND\s+", v):
                            val = re.split(r"[:=]", part, 1)[-1].strip().lower()
                            if len(val) >= 5:
                                out.append((val, path))
                            out.extend((w, path) for w in re.findall(r"[a-z]{5,}", val) if w not in GENERIC)
                    if k == "countermeasure":  # "Backplates with Retroreflective Borders" is also "backplates"
                        head = v.split()[0].lower()
                        if len(head) >= 6 and head not in GENERIC:
                            out.append((head, path))
            for k, v in o.items():
                walk(v, path + (str(k),))
        elif isinstance(o, (list, tuple)):
            for i, v in enumerate(o):
                walk(v, path + (i,))
    walk(facts, ())
    return out


# a number that is an age, a time of day, a speed, a distance, a duration or a house number is not a count the record
# could hold, so it is never bound to a label such as deaths ("a 30-year-old was killed")
NOT_A_COUNT = re.compile(r"\s*-?\s*(?:years?[- ]old|yrs?[- ]old|-year|a\.?m\.?\b|p\.?m\.?\b|o'clock|mph|km/h|miles?\b|"
                         r"feet\b|ft\b|meters?\b|metres?\b|minutes?\b|hours?\b|seconds?\b|days?\b|weeks?\b|"
                         r"months?\b|(?:st|nd|rd|th)\b|:\d\d)", re.I)
NOT_A_COUNT_BEFORE = re.compile(r"(?:\bage[ds]?|\baged|\bblock of|\bno\.|#|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?)\s*$", re.I)  # "October 19" is a date


class FactCheck:
    """Numbers a memo may use: those in the dossier. A number written next to a label (deaths, pedestrians injured,
    injury crashes, crashes, sites, crashes avoided, dollars) must also be the record's value for that label, so "29
    pedestrians were killed" is refused where the record has 29 pedestrians injured and no deaths. A count is bound to
    what its sentence names: a program's sites must be that program's, a pattern's crashes that pattern's, "in 2024"
    that year's count; a city-wide comparison figure is allowed only in a sentence that compares; a per-year figure
    must be a per-year value and a total a total; and "no", "zero" or "never" is a count of zero, refused where the
    record holds more (NML-Bench T18 found these holes)."""

    def __init__(self, facts: dict):
        # numbers in values and in field names (schools_400m, by_year keys such as 2022) are both in the dossier
        self.known = set(panel.numbers_in(facts)) | {panel._value(t) for t in panel.NUMBER.findall(
            json.dumps(facts, default=str))}
        self.paths = _paths(facts)
        self.named = _named(facts)
        self.since = min(_dates_named(facts, "since"), default=None)  # the record window's first day, if stated
        self.unknown = _not_recorded(facts)  # labels the record does not cover: no number or "none" may be claimed
        fields = _labelled(facts)
        self.by_label = {}
        for name, before, after, pattern in LABELS:
            vals = [v for k, vs in fields.items() if pattern and re.search(pattern, k)
                    and (name == "dollars" or not re.search(r"usd|harm|cost", k)) for v in vs]  # a count is not a cost
            if name == "dollars":  # "$8.8 million" and "$561,000" both name a dollar field
                vals += [v / 1e6 for v in vals] + [v / 1e3 for v in vals]
            if name == "deaths":  # "no one was killed" is about everyone: the total, not any one mode's count
                tot = [v for p_, k, v in self.paths if k in ("any_killed", "deaths_in_record")]
                modes = sum(v for p_, k, v in self.paths if k in ("pedestrian_killed", "cyclist_killed", "motorist_killed"))
                vals = [max(tot + [modes])] if (tot or modes) else []
            self.by_label[name] = vals or [0.0]  # an absent count is zero (the record lists only non-zero counts)
        self.known |= {round(v, 1) for v in self.by_label["dollars"]} | {0.0}  # "$8.8 million"; absent counts are 0
        # a percentage must be a share (0.28 -> 28%), a ratio's change (theta 0.833 -> 17%) or a field that is itself a
        # percentage or change; not any number that happens to be in the record ("129%" where 129 is a count)
        shares = [v for v in panel.numbers_in(facts) if 0 <= abs(v) <= 2]
        self.percents = ({100 * abs(v) for v in shares if abs(v) <= 1} | {100 * abs(1 - v) for v in shares if v > 0}
                         | {abs(v) for k, vs in fields.items() if re.search(r"pct|percent|share|rate|change|crf", k)
                            for v in vs})

    def text(self, text: str) -> list[str]:
        a, b = self._text(text), self._text(panel.normalise_decimals(text))
        return a if len(a) <= len(b) else b

    def _bound(self, sentence: str) -> list[tuple]:
        low = sentence.lower()
        return [path for name, path in self.named if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low)]

    def _percents(self, sentence: str, bound: list[tuple]) -> set[float]:
        """The percentages a sentence may state: shares, changes from ratios and percentage fields, of what it names
        when it names something; a simple before/after change only in a sentence that says it is one."""
        rows = [r for r in self.paths if any(r[0][:len(b)] == b for b in bound)] if bound else []
        rows = rows or self.paths
        naive = bool(NAIVE.search(sentence))
        compare = bool(COMPARE.search(sentence))
        out = set()
        for p, k, v in rows:
            if not compare and ("city" in k or any(isinstance(x, str) and BASELINE.search(x) for x in p)):
                continue  # the city-wide share is not this corner's
            if "naive" in k and not naive:
                continue
            if 0 <= abs(v) <= 1:
                out.add(100 * abs(v))
            if 0 < v <= 2 and not re.search(r"share|pct", k):
                out.add(100 * abs(1 - v))
            if re.search(r"pct|percent|share|rate|change|crf", k):
                out.add(abs(v))
        return out or self.percents

    def _values(self, name: str, pattern, sentence: str, tail: str, bound: list[tuple]) -> list[float] | None:
        """The values a labelled number may take in this sentence (None: the record has no such field to bind to)."""
        if name == "deaths":
            return self.by_label["deaths"]  # always the total across modes
        if pattern and not any(re.search(pattern, k) for _, k, _ in self.paths):
            return None if name == "sites" else ([0.0] if name != "dollars" else [])  # an absent count is zero
        compare = bool(COMPARE.search(sentence))
        rows = [(p, k, v) for p, k, v in self.paths
                if (compare or not any(isinstance(x, str) and BASELINE.search(x) for x in p))]
        if name == "crashes":  # a count of crashes: not a site count, a year, a share or a dollar figure
            rows = [r for r in rows if not re.search(r"sites|usd|harm|cost|share|pct|theta|ci95|cmf|year$|radius|^m$",
                                                    r[1]) or re.fullmatch(r"(19|20)\d\d", r[1])]
            words = re.match(r"\s*([a-z\- ]{3,30}?)\s*crash", tail, re.I)  # "37 rear-end crashes": that group's count
            if words:
                key = re.sub(r"[\s\-]+", "_", words.group(1).strip().lower())
                mine = [r for r in rows if r[1] == key or r[1].startswith(key + "_")]
                rows = mine or rows
        elif pattern:
            rows = [r for r in rows if re.search(pattern, r[1])]
        if bound:  # a sentence that names an item: its counts are that item's, when the item has such a field
            mine = [r for r in rows if any(r[0][:len(b)] == b for b in bound)]
            rows = mine or rows
        yr = re.search(r"\bin\s+((?:19|20)\d\d)\b", tail)
        if yr and name in ("crashes", "injury crashes"):
            mine = [r for r in rows if r[1] == yr.group(1)]
            rows = mine or rows
        if PER_YEAR.search(tail):
            mine = [r for r in rows if re.search(r"per_year|_year$|annual|avoided", r[1])]
            rows = mine or rows
        elif TOTAL.search(sentence):
            rows = [r for r in rows if not re.search(r"per_year|_year$|annual", r[1])]
        vals = [v for _, _, v in rows]
        if name == "dollars":
            vals += [v / 1e6 for v in vals] + [v / 1e3 for v in vals]
        return vals

    def _absences(self, sentence: str, bound: list[tuple]) -> list[str]:
        """"No pedestrians were killed", "zero evaluation sites", "never studied": a count of zero."""
        bad = []
        for name, _ in self.named:  # an item's own words ("... and no one hurt") are a description, not a count
            sentence = re.sub(re.escape(name), " ", sentence, flags=re.I)
        for m in NEG.finditer(sentence):
            after = sentence[m.end():m.end() + 45]
            for name, before, pat_after, pattern in LABELS:
                if pat_after and name not in ("crashes", "sites") and re.search(pat_after, after, re.I):
                    if name in self.unknown:
                        bad.append(f"says no {name}, but the record does not show {name} at all")
                        break
                    if not any(abs(v) < 1e-9 for v in self.by_label[name]):
                        bad.append(f"says no {name}, but the record has {max(self.by_label[name]):g}")
                    break
        local = re.search(r"\b(here|this corner|the corner|at this|recorded at)\b", sentence, re.I)
        if NEG.search(sentence) and COUNT_WORDS.search(sentence) and bound and not (local and not re.search(
                r"\bcrash", sentence[NEG.search(sentence).start():], re.I)):
            counts = [(p, k, v) for p, k, v in self.paths if any(p[:len(b)] == b for b in bound)
                      and re.fullmatch(r"crashes|sites|k|n|count|injury_crashes", k) and v > 0]
            if counts:
                bad.append(f"says none, but the record has {counts[0][2]:g} {counts[0][1]} for what it names")
        return bad

    def _text(self, text: str) -> list[str]:
        bad = []
        # a sentence ends at . ; ! ? followed by a space and a capital (or the end), never at a decimal point ("3.9")
        sentences = [(m.start(), m.end()) for m in re.finditer(r".+?(?:[.;!?](?=\s+[A-Z\u201c\"(])|$)", text, re.S)] \
            or [(0, len(text))]
        sentence_of = lambda i: next((text[a:b] for a, b in sentences if a <= i < b), text)
        for a, b in sentences:
            sent = text[a:b]
            bad += self._absences(sent, self._bound(sent))
        for m in panel.NUMBER.finditer(text):
            t = m.group(0)
            v, tol = panel._value(t), 0.5 * 10 ** -panel._decimals(t) + 1e-9
            tail = text[m.end():m.end() + 45]
            percent = tail.lstrip().startswith("%")
            if percent and re.match(r"\s*%\s*(confidence|interval|CI\b)", tail, re.I):
                continue  # "95% interval" names a confidence level, not a claim about the record
            if percent:  # "32%" is a share the record holds as 0.318, a change from a ratio, or a percentage field
                sent = sentence_of(m.start())
                if not any(abs(k - abs(v)) <= tol for k in self.percents):
                    bad.append(f"{t}% is not a share or change in the record")
                elif not any(abs(k - abs(v)) <= tol for k in self._percents(sent, self._bound(sent))):
                    bad.append(f"{t}% is not a share or change of what this sentence names")
                continue
            if NOT_A_COUNT.match(tail) or NOT_A_COUNT_BEFORE.search(text[max(0, m.start() - 12):m.start()]):
                if not any(abs(k - v) <= tol for k in self.known):
                    bad.append(f"number {t} is not in the dossier")
                continue  # an age, a time, a speed, a distance or an address: never a count from the record
            if not any(abs(k - v) <= tol for k in self.known):
                head, clause = text[max(0, m.start() - 30):m.start()], re.split(r"[,;]", tail, 1)[0]
                named = next((name for name, before, after, _ in LABELS if self.by_label.get(name) and name != "dollars"
                              and ((before and re.search(before, head, re.I)) or (after and re.search(after, clause, re.I)))),
                             None)
                has = sorted(set(self.by_label.get(named) or []), reverse=True)[:3] if named != "crashes" else []
                bad.append(f"{t}: the record does not show {named}" if named in self.unknown else
                           f"{t} is not the record's number of {named}" +
                           (f" (the record has {', '.join(f'{x:g}' for x in has)})" if has else
                            " for what this sentence names") if named
                           else f"number {t} is not in the dossier")
                continue
            if len(t) == 4 and t[:2] in ("19", "20"):
                continue  # years carry no label
            head = text[max(0, m.start() - 30):m.start()]
            sent = sentence_of(m.start())
            tail = re.split(r"[,;]", tail, 1)[0]  # the number's own clause: "129 injury crashes, about 26 a year"
            for name, before, after, pattern in LABELS:
                if (before and re.search(before, head, re.I)) or (after and re.search(after, tail, re.I)):
                    if name in self.unknown:
                        bad.append(f"{t}: the record does not show {name}")
                        break
                    if name in ("crashes", "injury crashes") and panel._decimals(t) and not PER_YEAR.search(tail):
                        bad.append(f"{t} is a rate or share written as a count of crashes")
                        break
                    vals = self._values(name, pattern, sent, tail, self._bound(sent))
                    if vals is not None and not any(abs(k - v) <= tol for k in vals):
                        bad.append(f"{t} is not the record's number of {name} for what this sentence names")
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
