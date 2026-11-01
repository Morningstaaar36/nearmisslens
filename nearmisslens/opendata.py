"""One engine for any city's open crash and safety-plan data. A city is not code but an adapter in the registry
(nearmisslens/data/registry.json): where the dataset lives (Socrata or ArcGIS), and which of its fields hold the
date, the injuries and deaths by road-user mode, the crash type and the conditions. Seed adapters were written by hand
for New York, Washington DC, Chicago and Los Angeles; the data agent (datascout.py) writes new ones for other cities
and they are kept only if they pass the validation checks below."""
from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter
from pathlib import Path

from . import context

REGISTRY = Path(__file__).resolve().parent / "data" / "registry.json"
MODES = ("pedestrian", "cyclist", "motorist", "any")
PAGE = 2000


def load_registry() -> list[dict]:
    return json.loads(REGISTRY.read_text())["adapters"] if REGISTRY.exists() else []


def load_cities() -> list[dict]:
    """The places the registry knows: id, name, bounding box and the transportation agency's name."""
    return json.loads(REGISTRY.read_text()).get("cities", []) if REGISTRY.exists() else []


def save_city(city: dict) -> None:
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"adapters": []}
    reg["cities"] = [c for c in reg.get("cities", []) if c["id"] != city["id"]] + [city]
    REGISTRY.write_text(json.dumps(reg, indent=1))


def city(city_id: str | None) -> dict | None:
    return next((c for c in load_cities() if c["id"] == city_id), None)


def adapter(adapter_id: str) -> dict | None:
    return next((a for a in load_registry() if a["id"] == adapter_id), None)


def adapters_of(city_id: str, kind: str) -> list[dict]:
    return [a for a in load_registry() if a.get("city") == city_id and a["kind"] == kind]


def save_adapter(adapter: dict) -> None:
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"adapters": []}
    reg["adapters"] = [a for a in reg["adapters"] if a["id"] != adapter["id"]] + [adapter]
    REGISTRY.write_text(json.dumps(reg, indent=1))


def adapters_for(lat: float, lon: float, kind: str) -> list[dict]:
    """Adapters of a kind that cover the point: by their own box, else their city's box; an adapter with neither
    (a global source such as OpenStreetMap) covers every point."""
    out = []
    for a in load_registry():
        if a["kind"] != kind:
            continue
        box = a.get("bbox") or (city(a.get("city")) or {}).get("bbox")
        if box is None and a.get("city") is None:
            out.append(a)
            continue
        if box is None:
            continue
        s, w, n, e = box
        if s <= lat <= n and w <= lon <= e:
            out.append(a)
    return out


def _since(years: int) -> dt.date:
    from .config import since
    return since(years)


def _date(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.utcfromtimestamp(v / 1000).date()
    text = str(v).strip()
    if text.isdigit() and len(text) >= 11:  # epoch milliseconds written as text
        return dt.datetime.utcfromtimestamp(int(text) / 1000).date()
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def rows_near(a: dict, lat: float, lon: float, radius_m: float, since: dt.date | None = None) -> list[dict]:
    """Raw records within radius_m of the point (and, for Socrata, since the date), from either platform."""
    if a["platform"] == "socrata":
        where = f"within_circle({a['geo_field']},{lat},{lon},{radius_m})"
        if since and a.get("date_field"):
            from .config import asof
            where += (f" AND {a['date_field']} >= '{since.isoformat()}'"
                      f" AND {a['date_field']} < '{(asof() + dt.timedelta(days=1)).isoformat()}'")
        js, _ = context.fetch(a["endpoint"], {"$where": where, "$limit": 5000})
        return js if isinstance(js, list) else []
    rows, offset = [], 0
    while True:
        js, _ = context.fetch(f"{a['endpoint']}/query", {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326, "distance": radius_m,
            "units": "esriSRUnit_Meter", "outFields": "*", "returnGeometry": "false", "f": "json",
            "resultOffset": offset, "resultRecordCount": PAGE, "where": a.get("where", "1=1")})
        feats = [f["attributes"] for f in js.get("features", [])]
        rows += feats
        # servers cap a page at their own maxRecordCount (often 1000) and flag exceededTransferLimit
        if not feats or not js.get("exceededTransferLimit"):
            break
        offset += len(feats)
    if since and a.get("date_field"):
        from .config import asof
        end = asof()
        rows = [r for r in rows if since <= (_date(r.get(a["date_field"])) or dt.date.min) <= end]
    return rows


def rows_all(a: dict, fields: list[str] | None = None, page: int = 50_000) -> list[dict]:
    """Every record of a dataset with its location as _lat/_lon (the point, or a line's middle vertex), from either
    platform; responses are cached like every other request."""
    rows = []
    if a["platform"] == "socrata":
        params = {"$limit": page}
        if a.get("where"):
            params["$where"] = a["where"]
        if fields:
            params["$select"] = ",".join(dict.fromkeys(fields + [a["geo_field"]] if a.get("geo_field") else fields))
        offset = 0
        while True:
            js, _ = context.fetch(a["endpoint"], {**params, "$offset": offset, "$order": ":id"})
            js = js if isinstance(js, list) else []
            rows += js
            if len(js) < page:
                break
            offset += page
    else:
        offset = 0
        while True:
            js, _ = context.fetch(f"{a['endpoint']}/query", {
                "where": a.get("where", "1=1"), "outFields": ",".join(fields) if fields else "*",
                "returnGeometry": "true", "outSR": 4326, "f": "json", "resultOffset": offset,
                "resultRecordCount": 2000})
            feats = js.get("features", [])
            rows += [{**f.get("attributes", {}), "_geometry": f.get("geometry")} for f in feats]
            if not feats or not js.get("exceededTransferLimit"):
                break
            offset += len(feats)
    for r in rows:
        r["_lat"], r["_lon"] = point_of(r, a) or (None, None)
    return rows


def point_of(r: dict, a: dict) -> tuple[float, float] | None:
    """A record's location: explicit latitude/longitude fields, a GeoJSON or Socrata location value, or an ArcGIS
    geometry (a line or polygon gives its middle vertex)."""
    try:
        if a.get("lat_field") and r.get(a["lat_field"]) not in (None, ""):
            return float(r[a["lat_field"]]), float(r[a["lon_field"]])
        g = r.get(a.get("geo_field", "")) if a.get("geo_field") else None
        if isinstance(g, dict):
            if "latitude" in g:
                return float(g["latitude"]), float(g["longitude"])
            c = g.get("coordinates")
            while isinstance(c, list) and c and isinstance(c[0], list):
                c = c[len(c) // 2]
            if isinstance(c, list) and len(c) >= 2:
                return float(c[1]), float(c[0])
        g = r.get("_geometry")
        if isinstance(g, dict):
            if "x" in g:
                return float(g["y"]), float(g["x"])
            if g.get("points"):
                return float(g["points"][0][1]), float(g["points"][0][0])
            for k in ("paths", "rings"):
                if g.get(k):
                    v = g[k][0][len(g[k][0]) // 2]
                    return float(v[1]), float(v[0])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def value_at(a: dict, lat: float, lon: float) -> str | None:
    """The value of the adapter's field for the polygon that contains the point (a district number, say)."""
    if a["platform"] == "socrata":
        js, _ = context.fetch(a["endpoint"], {"$select": a["field"],
                                             "$where": f"intersects({a['geo_field']},'POINT ({lon} {lat})')"})
        rows = js if isinstance(js, list) else []
    else:
        js, _ = context.fetch(f"{a['endpoint']}/query", {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": a["field"], "returnGeometry": "false", "f": "json"})
        rows = [f["attributes"] for f in js.get("features", [])]
    return str(rows[0][a["field"]]) if rows and rows[0].get(a["field"]) not in (None, "") else None


def office_from(a: dict, value: str) -> dict | None:
    """An office adapter's value as an addressee. A 'split' value encodes a prefix and a number (NYC's boro_cd 202 is
    the Bronx, board 2); numbers above max_number have no office (parks and other joint areas)."""
    fields, area = {"value": value}, None
    if a.get("split"):
        v = int(float(value))
        prefix, number = a["split"]["names"].get(str(v // a["split"]["by"])), v % a["split"]["by"]
        if prefix is None or number > a["split"].get("max_number", 10 ** 9):
            return None
        fields.update(prefix=prefix, number=number)
        area = prefix
    elif str(value).replace(".", "", 1).isdigit():
        fields["value"] = int(float(value))
    out = {"office": a["template"].format(**fields), "role": a.get("role"), "source": a["source"]}
    if area:
        out["area"] = area
    if a.get("contact"):
        out["contact"] = a["contact"].format(**fields)
    if a.get("salutation"):  # how a letter greets this office ("Council Member", "members of {office}")
        out["salutation"] = a["salutation"].format(office=out["office"], **fields)
    return out


def offices_at(lat: float, lon: float) -> list[dict]:
    """Who can request work at this point, from the office adapters (district boundaries) that cover it."""
    out = []
    for a in adapters_for(lat, lon, "office"):
        v = value_at(a, lat, lon)
        o = office_from(a, v) if v is not None else None
        if o:
            out.append(o)
    return out


def _sum(r: dict, fields: list[str]) -> float:
    return sum(_num(r.get(f)) for f in fields or [])


def _text(r: dict, fields: list[str]) -> str:
    return " ".join(str(r.get(f) or "") for f in fields or []).lower()


def crash_summary(a: dict, lat: float, lon: float, radius_m: float = 100, years: int = 5) -> dict:
    """The common crash profile from any crash adapter: counts, injuries and deaths by mode, crash groups, and the
    share of crashes in darkness and on wet or icy surfaces."""
    since = _since(years)
    rows = rows_near(a, lat, lon, radius_m, since)
    inj, kil = a.get("injured", {}), a.get("killed", {})
    sums = Counter()
    injury_crashes, groups, factors, years_c = 0, Counter(), Counter(), Counter()
    dark = wet = 0
    for r in rows:
        d = _date(r.get(a.get("date_field")))
        years_c[str(d.year) if d else "unknown"] += 1
        per = {}
        for mode in MODES:
            per[f"{mode}_injured"] = _sum(r, inj.get(mode, []))
            per[f"{mode}_killed"] = _sum(r, kil.get(mode, []))
        for k, v in per.items():
            sums[k] += v
        if any(v > 0 for v in per.values()) or _sum(r, a.get("serious_injured", [])) > 0:
            injury_crashes += 1
        kind = _text(r, a.get("crash_type_fields", []))
        fac = _text(r, a.get("factor_fields", []))
        if per["pedestrian_injured"] + per["pedestrian_killed"] > 0 or _sum(r, a.get("pedestrian_involved", [])) > 0 \
                or "pedestrian" in kind:
            groups["pedestrian"] += 1
        if per["cyclist_injured"] + per["cyclist_killed"] > 0 or _sum(r, a.get("cyclist_involved", [])) > 0 \
                or "cycl" in kind or "bicycl" in kind:
            groups["cyclist"] += 1
        if "rear" in kind or "following too closely" in fac:
            groups["rear_end"] += 1
        if "angle" in kind or "turn" in kind:
            groups["angle_turning"] += 1
        light = _text(r, a.get("light_fields", []))
        surface = _text(r, a.get("surface_fields", []))
        dark += "dark" in light
        wet += any(w in surface for w in ("wet", "ice", "snow", "slush"))
        for f in a.get("factor_fields", []):
            v = str(r.get(f) or "").strip()
            if v.lower() in ("y", "yes", "true", "1"):  # a flag field: the field name is the factor
                factors[f.lower()] += 1
            elif v and v.lower() not in ("unspecified", "does not apply", "unknown", "n", "no", "false", "none", "0"):
                factors[v] += 1
    n = len(rows)
    from .config import asof
    return {"source": a["source"], "adapter": a["id"], "radius_m": radius_m, "since": since.isoformat(),
            "asof": asof().isoformat(),
            "crashes": n, "injury_crashes": injury_crashes, "by_year": dict(sorted(years_c.items())),
            **{k: int(v) for k, v in sums.items() if v}, "crash_groups": dict(groups),
            "crash_type_recorded": bool(a.get("crash_type_fields")),
            "dark_share": round(dark / n, 3) if n and a.get("light_fields") else None,
            "wet_share": round(wet / n, 3) if n and a.get("surface_fields") else None,
            "top_factors": [{"factor": f, "crashes": c} for f, c in factors.most_common(3)],
            "factor_counts": dict(factors.most_common(15))}


def projects_near(a: dict, lat: float, lon: float, radius_m: float | None = None) -> list[dict]:
    rows = rows_near(a, lat, lon, radius_m or a.get("radius_m", 150))
    out = []
    for r in rows:
        d = _date(r.get(a.get("date_field"))) if a.get("date_field") else None
        y = r.get(a.get("year_field")) if a.get("year_field") else None
        year = int(y) if str(y or "").isdigit() else (d.year if d else None)
        from .config import asof
        out.append({"name": str(r.get(a.get("name_field")) or a.get("label") or a["id"]), "year": year,
                    "dataset": a["id"], **({"planned": True} if year and year > asof().year else {})})
    return out


def designated_near(a: dict, lat: float, lon: float, radius_m: float | None = None) -> list[str]:
    rows = rows_near(a, lat, lon, radius_m or a.get("radius_m", 150))
    return [str(r.get(a.get("name_field")) or a.get("label") or a["id"]) for r in rows]


def validate_crash_adapter(a: dict, lat: float, lon: float) -> dict:
    """Checks before an adapter is trusted: records come back near a point inside its area, dates parse and are
    recent, and the mapped injury fields hold numbers."""
    problems = []
    try:
        rows = rows_near(a, lat, lon, 400)
    except Exception as e:  # an unusable endpoint or field name
        return {"ok": False, "problems": [f"query failed: {type(e).__name__}: {e}"]}
    if not rows:
        problems.append("no records within 400 m of a point in the area")
    dates = [d for d in (_date(r.get(a.get("date_field"))) for r in rows) if d]
    if rows and not dates:
        problems.append(f"date field {a.get('date_field')!r} does not parse")
    if dates and max(dates) < _since(3):
        problems.append(f"latest record is {max(dates)}: the dataset looks stale")
    fields = [f for m in (a.get("injured", {}), a.get("killed", {})) for fs in m.values() for f in fs]
    if not fields:
        problems.append("no injury or death fields mapped")
    for f in fields:
        vals = [r.get(f) for r in rows[:50] if r.get(f) not in (None, "")]
        if rows and vals and not all(isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit() for v in vals):
            problems.append(f"field {f!r} is not numeric")
        if rows and f not in rows[0]:
            problems.append(f"field {f!r} is not in the records")
    return {"ok": not problems, "problems": problems, "records_near": len(rows),
            "latest": max(dates).isoformat() if dates else None}


def bbox_around(lat: float, lon: float, km: float = 25) -> list[float]:
    d = km / 111.32
    return [lat - d, lon - d / math.cos(math.radians(lat)), lat + d, lon + d / math.cos(math.radians(lat))]
