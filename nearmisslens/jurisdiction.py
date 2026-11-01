"""Who must act at a junction: who owns each road, and who can ask for the work.

1. A jurisdiction adapter in the registry (a road-inventory layer with an owner field) gives the owner of every
   listed road within a few metres, mapped to an agency by the adapter's "owners" table; "city" means the registry
   city's own transportation agency.
2. The junction's named streets that the inventory does not list are city streets when the adapter says it covers
   only routes ("inferred"); without an adapter, OpenStreetMap route tags say whether a road is a signed state or US
   route ("designation only").
3. The office adapters (council districts, community boards) say who can request the work.

No party is listed without the dataset row behind it; when sources disagree, both are shown."""
from __future__ import annotations

import re

from . import context, opendata


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    for a, b in ((" avenue", " ave"), (" boulevard", " blvd"), (" street", " st"), (" road", " rd"),
                 (" parkway", " pkwy"), (" expressway", " exp"), (" east ", " e "), (" west ", " w "),
                 (" north ", " n "), (" south ", " s ")):
        n = (" " + n + " ").replace(a + " ", b + " ").strip()
    return " ".join(n.split())


def _agency(label: str, city: dict | None, fields: dict) -> str:
    if label == "city":
        return (city or {}).get("agency") or "the city's transportation department"
    return label.format(**fields)


def owners(lat: float, lon: float, streets: list[str]) -> dict:
    """Road owners near the point from the jurisdiction adapters, and the junction's streets they do not list."""
    city = opendata.city(context.city_of(lat, lon))
    found, listed = [], set()
    for a in opendata.adapters_for(lat, lon, "jurisdiction"):
        js, _ = context.fetch(f"{a['endpoint']}/query", {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "distance": a.get("radius_m", 30), "units": "esriSRUnit_Meter", "returnGeometry": "false", "f": "json",
            "outFields": ",".join([a["name_field"], a["owner_field"], a.get("maint_field", a["owner_field"]),
                                   a.get("region_field", a["owner_field"]), *a.get("route_fields", [])])})
        for f in js.get("features", []):
            r = f.get("attributes", {})
            code = r.get(a["owner_field"])
            if not code:
                continue
            route = " ".join(str(r.get(k) or "") for k in a.get("route_fields", [])).strip()
            name = r.get(a["name_field"])
            road = f"{name} ({route})" if name and route else (name or route or "an unnamed segment")
            label = a.get("owners", {}).get(code, code)
            party = _agency(label, city, {"region": r.get(a.get("region_field", ""), "")})
            found.append({"party": party, "role": "owner", "road": road, "route": route or None,
                          "basis": {"dataset": a["source"], "field": a["owner_field"], "value": code},
                          "confidence": "recorded"})
            listed.add(_norm(name or road))
        # streets of the junction the inventory does not list: city streets, when it lists only routes
        if a.get("covers") and city:
            for s in streets:
                if s and _norm(s) not in listed:
                    found.append({"party": city.get("agency") or "the city's transportation department",
                                  "role": "owner", "road": s, "route": None,
                                  "basis": {"dataset": a["source"], "field": a["name_field"],
                                            "value": f"not listed ({a['covers']})"},
                                  "confidence": "inferred"})
    return {"owners": _merge(found), "adapter": bool(found)}


def osm_designations(street: dict | None, city: dict | None) -> list[dict]:
    """Without a jurisdiction adapter: OpenStreetMap route references (state or US routes) on the junction's roads."""
    out = []
    for r in (street or {}).get("roads", []):
        ref = " ".join(r.get("ref", []) or [])
        if re.search(r"\b(I|US|[A-Z]{2}|SR|CA|NY)\s?-?\d+", ref):
            out.append({"party": "the state transportation department (route designation only; confirm ownership)",
                        "role": "possible owner", "road": r["name"], "route": ref,
                        "basis": {"dataset": "OpenStreetMap", "field": "ref", "value": ref},
                        "confidence": "designation only"})
        elif city:
            out.append({"party": city.get("agency") or "the city's transportation department", "role": "owner",
                        "road": r["name"], "route": None,
                        "basis": {"dataset": "OpenStreetMap", "field": "ref", "value": "no route reference"},
                        "confidence": "inferred"})
    return _merge(out)


def _merge(rows: list[dict]) -> list[dict]:
    """One row per party and confidence, with every road it covers (an unnamed segment of a route that is also
    listed by name is not repeated)."""
    named = {r["route"] for r in rows if r.get("route") and r["road"] != r["route"]}
    out: dict[tuple, dict] = {}
    for r in rows:
        if r["road"] == r.get("route") and r["road"] in named:
            continue
        k = (r["party"], r["confidence"])
        if k not in out:
            out[k] = {**r, "roads": []}
        if r["road"] not in out[k]["roads"]:
            out[k]["roads"].append(r["road"])
    for v in out.values():
        v.pop("road", None)
    return merge_parties(list(out.values()))


def merge_parties(rows: list[dict]) -> list[dict]:
    """One entry per agency: a party that owns recorded roads and inferred ones (the city DOT, typically) is listed
    once, with its recorded basis and the inferred roads named separately, so "two owners" means two agencies."""
    out: dict[str, dict] = {}
    for r in rows:
        p = r["party"]
        if p not in out:
            out[p] = {**r, "roads": list(r["roads"]), "inferred_roads": list(r["roads"]) if r["confidence"] == "inferred" else []}
            continue
        o = out[p]
        o["roads"] += [x for x in r["roads"] if x not in o["roads"]]
        if r["confidence"] == "inferred":
            o["inferred_roads"] += [x for x in r["roads"] if x not in o["inferred_roads"]]
        elif o["confidence"] != "recorded":  # a recorded row gives the entry its basis
            o.update(confidence="recorded", basis=r["basis"], route=r.get("route"))
    for o in out.values():
        if o["confidence"] == "inferred" or not o["inferred_roads"]:
            o.pop("inferred_roads")
    return list(out.values())


def who_must_act(lat: float, lon: float, streets: list[str], street_layout: dict | None = None) -> dict:
    """Owners (who builds), and the offices that can request the work, each with its basis."""
    city = opendata.city(context.city_of(lat, lon))
    own = owners(lat, lon, streets)
    rows = own["owners"] if own["adapter"] else osm_designations(street_layout, city)
    if not rows and city:  # no owner dataset and no street layout: the junction's named streets, as city streets
        rows = _merge([{"party": city.get("agency") or "the city's transportation department", "role": "owner",
                        "road": s, "route": None, "confidence": "inferred",
                        "basis": {"dataset": "the junction's street names", "field": "name",
                                  "value": "no road-owner dataset registered for this city"}} for s in streets if s])
    requesters = [{"party": o["office"], "role": o.get("role") or "office", "contact": o.get("contact"),
                   "salutation": o.get("salutation"),
                   "basis": {"dataset": o.get("source"), "field": "district", "value": o["office"]},
                   "confidence": "recorded"} for o in opendata.offices_at(lat, lon) if o.get("source")]
    rows = merge_parties(rows)
    return {"owners": rows, "requesters": requesters,
            "summary": "; ".join(f"{r['party']} ({', '.join(r['roads'])})" for r in rows) or "no road owner found"}
