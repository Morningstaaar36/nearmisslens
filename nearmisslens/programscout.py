"""Program agent: finds a city's dated street-safety programs and hands them to the causal gate.

1. Search the public catalogs (ArcGIS Online, Socrata Discovery API) for treatment datasets named after the city:
   leading pedestrian intervals, crosswalks, traffic calming, refuge islands, bike lanes and others.
2. Read each layer's fields, record count and two sample records.
3. A model (Muse Spark Open on Baseten by default) decides whether the layer is a dated treatment program and maps it:
   the install-date field, an optional filter (for example "installed" status), a short label, and the FHWA Proven
   Safety Countermeasure it is, if any.
4. A validator inside its submit tool accepts the mapping only if the fields exist, the filter runs, at least 100
   records have install dates that parse inside the city's crash record (with three years on each side), and most
   records lie inside the city. Errors go back to the model to fix.
5. The accepted adapter is saved to the registry with its catalog id and the validation result; `nml gate CITY` then
   runs the registered T13 design on every program the city has."""
from __future__ import annotations

import datetime as dt
import json
import re

from . import context, countermeasures, opendata
from .agent import Tool, run_agent

MODEL = "muse-spark-1.3-contributor"  # served by Muse Spark Open when the open-weights client is used
QUERIES = ("leading pedestrian interval", "crosswalk", "traffic calming", "speed hump", "pedestrian refuge island",
           "curb extension", "bike lane", "speed camera", "vision zero improvements", "pedestrian safety")
MIN_DATED = 100
_COVERAGE: dict[str, tuple[int, int]] = {}  # city -> first and last month of its crash record


def candidates(city: dict, per_query: int = 6) -> list[dict]:
    """Treatment-like layers from ArcGIS Online (every layer of each service found) and Socrata."""
    name = city["name"].split(",")[0]
    out, seen = [], set()
    for q in QUERIES:
        try:
            js, _ = context.fetch("https://www.arcgis.com/sharing/rest/search",
                                  {"q": f'{q} {name} type:"Feature Service"', "num": per_query, "f": "json"})
        except RuntimeError:
            js = {}
        for r in js.get("results", []):
            url = (r.get("url") or "").rstrip("/")
            if not re.search(r"/(FeatureServer|MapServer)(/\d+)?$", url) or r["id"] in seen:
                continue
            seen.add(r["id"])
            base = re.sub(r"/\d+$", "", url)
            try:
                info, _ = context.fetch(base, {"f": "json"})
            except RuntimeError:
                continue
            for lyr in info.get("layers", [])[:20]:
                out.append({"platform": "arcgis", "id": f"{r['id']}-{lyr['id']}", "catalog_id": r["id"],
                            "name": f"{r['title']} / {lyr['name']}", "endpoint": f"{base}/{lyr['id']}"})
        try:
            js, _ = context.fetch("https://api.us.socrata.com/api/catalog/v1",
                                  {"q": f"{q} {name}", "only": "dataset", "limit": per_query})
        except RuntimeError:
            js = {}
        for r in js.get("results", []):
            res, meta = r["resource"], r.get("metadata", {})
            if res["id"] in seen:
                continue
            seen.add(res["id"])
            out.append({"platform": "socrata", "id": res["id"], "catalog_id": res["id"], "name": res["name"],
                        "endpoint": f"https://{meta.get('domain', '')}/resource/{res['id']}.json",
                        "columns": list(zip(res.get("columns_field_name", []), res.get("columns_datatype", [])))})
    return out


def describe(c: dict) -> dict | None:
    """Fields (with types), geometry, record count and two sample records; None for layers with no locations."""
    if c["platform"] == "socrata":
        geo = [n for n, t in c.get("columns", []) if t in ("Point", "Location", "MultiPoint", "Line", "MultiLine")]
        if not geo:
            return None
        sample, _ = context.fetch(c["endpoint"], {"$limit": 2})
        cnt, _ = context.fetch(c["endpoint"], {"$select": "count(*) as n"})
        if not isinstance(sample, list) or not sample:
            return None
        return {**c, "geo_field": geo[0], "fields": [f"{n} ({t})" for n, t in c["columns"]],
                "count": int((cnt or [{}])[0].get("n", 0)) if isinstance(cnt, list) else None,
                "sample": [{k: v for k, v in r.items() if not isinstance(v, dict)} for r in sample]}
    info, _ = context.fetch(c["endpoint"], {"f": "json"})
    if info.get("type") not in ("Feature Layer", None) or not info.get("geometryType"):
        return None
    sample, _ = context.fetch(f"{c['endpoint']}/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                                        "resultRecordCount": 2, "f": "json"})
    cnt, _ = context.fetch(f"{c['endpoint']}/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"})
    rows = [f["attributes"] for f in sample.get("features", [])]
    if not rows:
        return None
    return {**c, "geometry": info["geometryType"], "count": cnt.get("count"),
            "fields": [f"{f['name']} ({f['type'].replace('esriFieldType', '')})" for f in info.get("fields", [])],
            "sample": rows}


def _psc_names() -> list[str]:
    return [i["name"] for i in countermeasures.psc_items()]


MAPPING = {"type": "object", "additionalProperties": False,
           "required": ["is_treatment_program", "date_field", "where", "label", "countermeasure", "reason"],
           "properties": {"is_treatment_program": {"type": "boolean"}, "date_field": {"type": "string"},
                          "where": {"type": "string"}, "label": {"type": "string"},
                          "countermeasure": {"type": "string"}, "reason": {"type": "string"}}}
INSTRUCTIONS = (
    "You decide whether a city's open dataset records a street-safety treatment program: one record per place where "
    "the city installed something (a signal change, crosswalk, refuge island, speed hump, bike lane, camera...), with "
    "the date it was installed or went live. If it does, give: the field holding the install, completion or go-live "
    "date (a date field, not a year or a planned date); a filter that keeps only installed records, written as a "
    "where-clause on the dataset's own fields, or an empty string if every record is installed; a short plain label "
    "(e.g. 'leading pedestrian intervals'); and the FHWA Proven Safety Countermeasure it is, exactly as written in "
    "this list, or an empty string if none fits: {psc}. Use only field names from the list. Call finish once; if it "
    "is refused, fix what the errors say.")


def _dates(a: dict) -> list[dt.date]:
    rows = opendata.rows_all(a, fields=[a["date_field"]]) if a["platform"] == "socrata" else opendata.rows_all(a)
    return [d for d in (opendata._date(r.get(a["date_field"])) for r in rows) if d], rows


def validate(a: dict, city: dict) -> dict:
    """Checks before a program adapter is trusted: the filter runs, at least MIN_DATED install dates parse inside the
    city's crash record with three years on each side, and most records are inside the city."""
    from . import treatments
    problems = []
    try:
        dates, rows = _dates(a)
    except Exception as e:  # an unusable field name or filter
        return {"ok": False, "problems": [f"query failed: {type(e).__name__}: {e}"]}
    try:
        if city["id"] not in _COVERAGE:
            cr = treatments.crashes(city["id"])
            _COVERAGE[city["id"]] = (int(cr["month"].min()), int(cr["month"].max()))
        lo, hi = _COVERAGE[city["id"]][0] + 36, _COVERAGE[city["id"]][1] - 36
    except Exception:
        from .config import asof
        lo, hi = 2012 * 12, (asof().year - 3) * 12
    usable = [d for d in dates if lo <= d.year * 12 + d.month - 1 <= hi]
    if len(usable) < MIN_DATED:
        problems.append(f"only {len(usable)} records have an install date inside the usable period "
                        f"({treatments._label(lo)} to {treatments._label(hi)}); at least {MIN_DATED} are needed")
    yearly = sum((d.month, d.day) in ((1, 1), (12, 31)) for d in usable)
    if usable and yearly >= 0.6 * len(usable):
        problems.append(f"{yearly} of {len(usable)} install dates fall on 1 January or 31 December: the dates look "
                        "year-precision, too coarse for monthly before/after windows")
    s, w, n, e = city["bbox"]
    located = [r for r in rows if r.get("_lat") is not None]
    inside = sum(s <= r["_lat"] <= n and w <= r["_lon"] <= e for r in located)
    if not located or inside < 0.8 * len(located):
        problems.append(f"{inside} of {len(located)} located records are inside {city['name']}")
    if a.get("countermeasure") and a["countermeasure"] not in _psc_names():
        problems.append(f"{a['countermeasure']!r} is not an FHWA Proven Safety Countermeasure name from the list")
    return {"ok": not problems, "problems": problems, "records": len(rows), "dated": len(dates),
            "usable_dated": len(usable), "first": min(dates).isoformat() if dates else None,
            "last": max(dates).isoformat() if dates else None}


def _adapter(d: dict, m: dict, city: dict) -> dict:
    a = {"id": f"auto-{city['id']}-{re.sub(r'[^a-z0-9]+', '-', m['label'].lower()).strip('-')}-{d['id'][:12]}",
         "kind": "project", "city": city["id"], "place": city["name"], "bbox": city["bbox"],
         "platform": d["platform"], "endpoint": d["endpoint"], "date_field": m["date_field"], "label": m["label"],
         "radius_m": 60, "source": f"{d['name']} ({d['platform']} {d['catalog_id']})"}
    if m["where"].strip():
        a["where"] = m["where"].strip()
    if m["countermeasure"].strip():
        a["countermeasure"] = m["countermeasure"].strip()
    if d["platform"] == "socrata":
        a["geo_field"] = d["geo_field"]
    return a


def map_and_validate(client, d: dict, city: dict, tag: str) -> tuple[dict | None, list]:
    names = {f.split(" (")[0] for f in d["fields"]}
    accepted, log = [], []

    def finish(**m) -> dict:
        if not m["is_treatment_program"]:
            accepted.append({"not_program": m["reason"]})
            return {"ok": True}
        if m["date_field"] not in names:
            log.append({"errors": [f"{m['date_field']!r} is not a field"]})
            return {"error": "the date field is not in the dataset", "errors": log[-1]["errors"]}
        a = _adapter(d, m, city)
        check = validate(a, city)
        log.append({"mapping": m, "validation": check})
        if not check["ok"]:
            return {"error": "the mapping fails validation on the real records", "errors": check["problems"]}
        accepted.append({"adapter": a, "mapping": m, "validation": check})
        return {"ok": True}

    tool = Tool("finish", "Submit the decision and mapping; it is checked against the real records.", MAPPING, finish)
    task = (f"City: {city['name']}. Dataset: {d['name']} ({d['platform']}, {d['endpoint']}), {d.get('count')} records"
            f"{', geometry ' + d['geometry'] if d.get('geometry') else ''}.\nFields: {json.dumps(d['fields'])}\n"
            f"Sample records: {json.dumps(d['sample'], default=str)[:5000]}")
    run_agent(client, MODEL, INSTRUCTIONS.format(psc="; ".join(_psc_names())), task, [tool], 6, 0.05, effort="low",
              tag=tag, escalate_after=3)
    return (accepted[-1] if accepted else None), log


def discover(client, city_id: str, save: bool = True, limit: int = 40, skip_known: bool = True) -> dict:
    """Find, map and validate every dated treatment program the catalogs list for a registry city."""
    city = opendata.city(city_id)
    if city is None:
        raise ValueError(f"{city_id} is not a registry city; add its crash data first (nml discover LAT LON)")
    known = {a["endpoint"].rstrip("/") for a in opendata.load_registry()}
    found, tried = [], []
    for c in candidates(city)[:limit]:
        if skip_known and c["endpoint"].rstrip("/") in known:
            tried.append({"candidate": c["name"], "skipped": "already in the registry"})
            continue
        try:
            d = describe(c)
        except Exception as e:  # a layer that will not answer
            tried.append({"candidate": c["name"], "rejected": f"{type(e).__name__}"})
            continue
        if d is None or not d.get("count"):
            tried.append({"candidate": c["name"], "rejected": "no located records"})
            continue
        got, log = map_and_validate(client, d, city, f"programscout {city_id} {c['id']}")
        if not got or "not_program" in got:
            why = (got or {}).get("not_program") or ("; ".join((log[-1].get("validation") or {}).get("problems", [])
                                                         or log[-1].get("errors", [])) if log else "no mapping")
            tried.append({"candidate": c["name"], "rejected": why, "attempts": len(log)})
            continue
        a = got["adapter"]
        a["provenance"] = {"found_by": "program agent", "catalog_id": c["catalog_id"], "model": MODEL,
                           "mapping_reason": got["mapping"]["reason"], "validation": got["validation"],
                           "attempts": len(log)}
        if save:
            opendata.save_adapter(a)
        known.add(a["endpoint"].rstrip("/"))
        found.append(a)
    return {"city": city_id, "found": found, "tried": tried}
