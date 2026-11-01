"""Requests residents and officials already made: a city's signal study requests (registry kind "study_requests"),
matched to the engineer's corners by their two street names.

Some fixes have been asked for and turned down. Where a request for a fix (e.g. a leading pedestrian interval) was
denied, the fix is still not recorded at the corner, and the corner's own record since then has the crashes the fix
addresses, the case can say so and the corner goes on a re-request list. Wording stays with what the record shows:
"denied on <date>; since then the record shows ...", never that the denial was wrong. Requests that name a street
without a cross street, or whose names match no corner, are not used."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import context, opendata
from .config import SETTINGS

ABBREV = {"AVENUE": "AV", "AVE": "AV", "STREET": "ST", "BOULEVARD": "BLVD", "ROAD": "RD", "PARKWAY": "PKWY",
          "PLACE": "PL", "EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S", "EXPRESSWAY": "EXPY", "EXPWY": "EXPY",
          "DRIVE": "DR", "LANE": "LN", "TURNPIKE": "TPKE", "HIGHWAY": "HWY", "SQUARE": "SQ", "CONCOURSE": "CONC",
          "BRIDGE": "BR", "TERRACE": "TER", "COURT": "CT", "PLAZA": "PLZ", "SAINT": "ST"}
PAGE = 50_000


def norm(name: str | None) -> str:
    """A street name reduced to a comparable form: upper case, ordinals and punctuation dropped, suffixes and
    directions abbreviated ("West 125th Street" -> "W 125 ST")."""
    s = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", (name or "").upper())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(ABBREV.get(w, w) for w in s.split())


def adapter(city: str) -> dict | None:
    found = opendata.adapters_of(city, "study_requests")
    return found[0] if found else None


def rows(a: dict) -> list[dict]:
    """Every request in the dataset, downloaded once into the data directory (free, no key)."""
    d = Path(SETTINGS.data_dir) / "study_requests" / a["id"]
    pages = sorted(d.glob("page_*.json"))
    if not pages:
        if SETTINGS.replay:
            raise FileNotFoundError(f"no request pages in {d} (replay mode does not download)")
        import httpx
        d.mkdir(parents=True, exist_ok=True)
        for k in range(50):
            with httpx.Client(headers=context.UA, timeout=300) as c:
                r = c.get(a["endpoint"], params={"$limit": PAGE, "$offset": k * PAGE, "$order": ":id"})
            r.raise_for_status()
            if not r.json():
                break
            (d / f"page_{k}.json").write_text(r.text)
        pages = sorted(d.glob("page_*.json"))
    return [x for p in pages for x in json.loads(p.read_text())]


def index(a: dict, requests: list[dict]) -> dict[frozenset, list[dict]]:
    """Requests by the unordered pair of normalised street names they name (main street with each cross street)."""
    f = a["fields"]
    out: dict[frozenset, list[dict]] = collections.defaultdict(list)
    for r in requests:
        main = norm(r.get(f["main"]))
        for k in f["cross"]:
            cross = norm(r.get(k))
            if main and cross and cross != main:
                out[frozenset((main, cross))].append(r)
    return out


def _denied(a: dict, r: dict) -> bool:
    return a["denied_when_status_has"].lower() in str(r.get(a["fields"]["status"]) or "").lower()


def corner(a: dict, idx: dict, case: dict) -> dict | None:
    """What was asked for at one corner and turned down, and the corner's record since. None when no request names
    the corner's two streets."""
    f = a["fields"]
    name = case["junction"]["name"].split(",")[0]
    streets = [norm(s) for s in name.split(" & ")]
    if len(streets) != 2:
        return None
    found = idx.get(frozenset(streets), [])
    if not found:
        return None
    fx = case["findings"]["choose_fixes"]
    cr = fx.get("crashes") or {}
    present = {x.get("countermeasure") for x in fx.get("in_place") or []}
    projects = {p.get("dataset") for p in case["findings"]["test_programs"].get("projects_here") or []}
    for p in projects:
        cm = (opendata.adapter(p or "") or {}).get("countermeasure")
        if cm:
            present.add(cm)
    since = cr.get("since")
    denials = []
    for r in found:
        if not _denied(a, r) or r.get(f["type"]) not in a["fix_requests"]:
            continue
        fix = a["fix_requests"][r.get(f["type"])]
        date = str(r.get(f["requested"]) or "")[:10] or None
        decided = str(r.get(f["status_date"]) or "")[:10] or None
        denials.append({"request": r.get(f["type"]), "fix": fix, "requested": date, "decided": decided,
                        "reference": r.get(f["id"]), "status": r.get(f["status"]),
                        "fix_recorded_now": bool(fix and fix in present),
                        "whole_window_after_decision": bool(decided and since and decided <= since)})
    return {"corner": name, "requests_naming_corner": len(found), "denials": sorted(denials, key=lambda x: x["decided"] or ""),
            "injury_crashes": cr.get("injury_crashes"), "pedestrians_injured": cr.get("pedestrian_injured", 0),
            "records_since": since}


def rerequest(c: dict) -> dict | None:
    """The re-request a corner warrants: a denied fix that is still not recorded there, with every crash in the
    case's window after the decision, and pedestrians hurt since. The claim is checked like any other."""
    open_ = [d for d in c["denials"] if d["fix"] and not d["fix_recorded_now"] and d["whole_window_after_decision"]]
    if not open_ or not c.get("pedestrians_injured"):
        return None
    d = open_[-1]
    facts = {"injury_crashes": c["injury_crashes"], "pedestrians_injured": c["pedestrians_injured"],
             "decided": d["decided"], "records_since": c["records_since"]}
    text = (f"A request for a {d['request'].lower()} here was turned down on {d['decided']}. None is recorded at "
            f"the corner now, and in the records since {c['records_since']} the corner had {c['injury_crashes']} "
            f"injury crashes with {c['pedestrians_injured']} pedestrians injured.")
    errors = context.FactCheck(facts).text(text)
    return {"corner": c["corner"], "fix": d["fix"], "request": d["request"], "decided": d["decided"],
            "reference": d["reference"], "text": text if not errors else None, "refused": errors, "facts": facts}


def build(city: str, cases: list[dict]) -> dict | None:
    a = adapter(city)
    if not a:
        return None
    idx = index(a, rows(a))
    per = [x for x in (corner(a, idx, c) for c in cases) if x]
    asks = list({x["corner"]: x for x in (rerequest(c) for c in reversed(per)) if x}.values())  # one per corner name
    by_type = collections.Counter(d["request"] for c in per for d in c["denials"])
    return {"source": a["source"], "dataset": a["id"], "corners": len(cases), "corners_matched": len(per),
            "corners_with_a_denied_fix_request": sum(1 for c in per if c["denials"]),
            "denied_fix_requests_by_type": dict(by_type),
            "rerequests": sorted(asks, key=lambda x: -x["facts"]["pedestrians_injured"]),
            "matching": "by the corner's two street names, normalised (suffixes, directions, ordinals); unmatched "
                        "corners are left out, not guessed"}
