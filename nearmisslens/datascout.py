"""Data agent: finds a city's open crash data and writes a registry adapter for it, so the copilot works in cities
nobody wired by hand.

1. Search the public catalogs (Socrata Discovery API, ArcGIS Online) for crash and collision datasets named after the
   place.
2. Read each candidate's fields and two sample records.
3. A model (Muse Spark Contributor, or Muse Spark Open on Baseten) maps the fields to the common schema in
   opendata.py through a strict tool call.
4. Deterministic checks (opendata.validate_crash_adapter) accept the adapter only if records come back near the point,
   dates parse and are recent, and the injury fields exist and are numeric; otherwise the next candidate is tried.
5. The accepted adapter is saved to the registry with its catalog id and the validation result, for a person to
   review."""
from __future__ import annotations

import json
import re

from . import context, opendata, panel
from .agent import Tool, run_agent
from .config import MODELS

MODEL = MODELS["reader"]
QUERIES = ("traffic crashes", "collisions", "motor vehicle crashes", "traffic collisions")
MAX_CANDIDATES = 6


def place_of(lat: float, lon: float) -> dict:
    js, _ = context.fetch("https://nominatim.openstreetmap.org/reverse",
                          {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10})
    a = js.get("address", {})
    return {"city": a.get("city") or a.get("town") or a.get("county") or "", "state": a.get("state", ""),
            "country": a.get("country_code", "")}


def _arcgis_layer(url: str) -> str | None:
    """A FeatureServer/MapServer URL as a point layer URL (layer 0 when a service is given)."""
    if re.search(r"/(FeatureServer|MapServer)/\d+$", url):
        return url
    if re.search(r"/(FeatureServer|MapServer)/?$", url):
        return url.rstrip("/") + "/0"
    return None


def candidates(place: dict) -> list[dict]:
    """Crash-like datasets from both catalogs, Socrata first (native radius queries)."""
    city = place["city"]
    out, seen = [], set()
    for q in QUERIES:
        js, _ = context.fetch("https://api.us.socrata.com/api/catalog/v1",
                              {"q": f"{q} {city}", "only": "dataset", "limit": 8})
        for r in js.get("results", []):
            res, meta = r["resource"], r.get("metadata", {})
            dom = meta.get("domain", "")
            if res["id"] in seen or res.get("type") not in ("dataset", None):
                continue
            seen.add(res["id"])
            out.append({"platform": "socrata", "id": res["id"], "name": res["name"], "domain": dom,
                        "endpoint": f"https://{dom}/resource/{res['id']}.json",
                        "columns": list(zip(res.get("columns_field_name", []), res.get("columns_datatype", [])))})
        js, _ = context.fetch("https://www.arcgis.com/sharing/rest/search",
                              {"q": f'{q} {city} type:"Feature Service"', "num": 8, "f": "json"})
        for r in js.get("results", []):
            layer = _arcgis_layer(r.get("url") or "")
            if not layer or r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append({"platform": "arcgis", "id": r["id"], "name": r["title"], "endpoint": layer})
    keep = [c for c in out if re.search(r"crash|collision|accident", c["name"], re.I)]
    return keep[:MAX_CANDIDATES * 2]


def describe(c: dict, lat: float, lon: float) -> dict | None:
    """Fields and two sample records of a candidate (None if it is not a point dataset with records)."""
    if c["platform"] == "socrata":
        geo = [n for n, t in c.get("columns", []) if t in ("Point", "Location")]
        if not geo:
            return None
        sample, _ = context.fetch(c["endpoint"], {"$limit": 2})
        if not isinstance(sample, list) or not sample:
            return None
        return {**c, "geo_field": geo[0], "fields": [n for n, _ in c["columns"]],
                "sample": [{k: v for k, v in r.items() if not isinstance(v, dict)} for r in sample]}
    info, _ = context.fetch(c["endpoint"], {"f": "json"})
    if info.get("geometryType") != "esriGeometryPoint":
        return None
    sample, _ = context.fetch(f"{c['endpoint']}/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                                        "resultRecordCount": 2, "f": "json"})
    rows = [f["attributes"] for f in sample.get("features", [])]
    if not rows:
        return None
    return {**c, "fields": [f["name"] for f in info.get("fields", [])], "sample": rows}


MAPPING = {"type": "object", "additionalProperties": False,
           "required": ["is_crash_records", "date_field", "injured", "killed", "crash_type_fields", "factor_fields",
                        "light_fields", "surface_fields", "pedestrian_involved", "cyclist_involved", "reason"],
           "properties": {
               "is_crash_records": {"type": "boolean"},
               "date_field": {"type": "string"},
               "injured": {"type": "object", "additionalProperties": False,
                           "required": ["pedestrian", "cyclist", "motorist", "any"],
                           "properties": {m: {"type": "array", "items": {"type": "string"}} for m in opendata.MODES}},
               "killed": {"type": "object", "additionalProperties": False,
                          "required": ["pedestrian", "cyclist", "motorist", "any"],
                          "properties": {m: {"type": "array", "items": {"type": "string"}} for m in opendata.MODES}},
               **{k: {"type": "array", "items": {"type": "string"}} for k in
                  ("crash_type_fields", "factor_fields", "light_fields", "surface_fields", "pedestrian_involved",
                   "cyclist_involved")},
               "reason": {"type": "string"}}}
INSTRUCTIONS = (
    "You map a city's open crash dataset to a common schema. From the field list and sample records, decide whether "
    "the dataset holds one record per traffic crash. If so, give: the crash date field; the numeric fields counting "
    "injured and killed people, split by pedestrian, cyclist and motorist where the dataset splits them, otherwise "
    "under 'any' (never put a field in two modes); fields describing crash type or manner of collision; contributing "
    "factor fields; light condition and road surface fields; numeric fields counting pedestrians or cyclists involved. "
    "Use only field names that appear in the list, and leave a list empty when no field fits. Call submit_mapping once.")


def _adapter(d: dict, m: dict, place: dict, lat: float, lon: float) -> dict:
    a = {"id": f"auto-{re.sub(r'[^a-z0-9]+', '-', place['city'].lower())}-{d['id']}", "kind": "crash",
         "place": f"{place['city']}, {place['state']}", "bbox": opendata.bbox_around(lat, lon),
         "platform": d["platform"], "endpoint": d["endpoint"], "date_field": m["date_field"],
         "source": f"{d['name']} ({d['platform']} {d['id']})",
         "injured": {k: v for k, v in m["injured"].items() if v},
         "killed": {k: v for k, v in m["killed"].items() if v},
         **{k: m[k] for k in ("crash_type_fields", "factor_fields", "light_fields", "surface_fields",
                              "pedestrian_involved", "cyclist_involved") if m[k]}}
    if d["platform"] == "socrata":
        a["geo_field"] = d["geo_field"]
    return a


def map_and_validate(client, d: dict, place: dict, lat: float, lon: float, tag: str) -> tuple[dict | None, list]:
    """The model maps the fields; the validator runs inside its submit tool, and its errors go back to the model to
    fix (at most three refusals, then the candidate is given up)."""
    names = set(d["fields"])
    accepted: list[dict] = []
    log: list[dict] = []

    def submit(**m) -> dict:
        if not m["is_crash_records"]:
            accepted.append({"not_crash": m["reason"]})
            return {"ok": True}
        bad = [f for f in [m["date_field"]] + [x for k in ("injured", "killed") for v in m[k].values() for x in v]
               + [x for k in ("crash_type_fields", "factor_fields", "light_fields", "surface_fields",
                              "pedestrian_involved", "cyclist_involved") for x in m[k]] if f and f not in names]
        if bad:
            log.append({"errors": [f"{f!r} is not a field" for f in bad]})
            return {"error": "fields not in the dataset", "errors": log[-1]["errors"]}
        a = _adapter(d, m, place, lat, lon)
        check = opendata.validate_crash_adapter(a, lat, lon)
        log.append({"mapping": m, "validation": check})
        if not check["ok"]:
            return {"error": "the mapping fails validation on real records", "errors": check["problems"],
                    "hint": "dates must be a date or epoch field; injury and death fields must hold numbers"}
        accepted.append({"adapter": a, "mapping": m, "validation": check})
        return {"ok": True}

    tool = Tool("finish", "Submit the field mapping; it is checked against real records.", MAPPING, submit)
    task = (f"Dataset: {d['name']} ({d['platform']}, {d['endpoint']}).\nFields: {json.dumps(d['fields'])}\n"
            f"Sample records: {json.dumps(d['sample'], default=str)[:6000]}")
    run_agent(client, MODEL, INSTRUCTIONS, task, [tool], 6, 0.05, effort="low", tag=tag, escalate_after=3)
    return (accepted[-1] if accepted else None), log


def discover(client, lat: float, lon: float, save: bool = True) -> dict:
    """Find, map and validate a crash adapter for the place around the point. Returns the adapter, or the reasons
    every candidate was turned down."""
    place = place_of(lat, lon)
    tried = []
    for c in candidates(place):
        d = describe(c, lat, lon)
        if d is None:
            tried.append({"candidate": c["name"], "rejected": "not a point dataset with records"})
            continue
        got, log = map_and_validate(client, d, place, lat, lon, f"datascout {place['city']} {c['id']}")
        if not got or "not_crash" in got:
            why = (got or {}).get("not_crash") or "; ".join(log[-1].get("errors") or log[-1].get("validation", {}).get(
                "problems", [])) if log else "no mapping"
            tried.append({"candidate": c["name"], "rejected": why, "attempts": len(log)})
            continue
        a = got["adapter"]
        a["city"] = context.city_of(lat, lon)  # a registry city's adapter, or none saved: add the city first
        a["provenance"] = {"found_by": "data agent", "catalog_id": c["id"], "model": MODEL,
                           "mapping_reason": got["mapping"]["reason"], "validation": got["validation"],
                           "attempts": len(log)}
        if save and a["city"]:
            opendata.save_adapter(a)
        elif save:
            return {"place": place, "adapter": a, "tried": tried, "not_saved": "no registry city covers this point; "
                    "add it first with nml add-city, then run discover again"}
        return {"place": place, "adapter": a, "tried": tried}
    return {"place": place, "adapter": None, "tried": tried}
