"""The city's action plan, built only from the engineer's saved cases (runs/engineer/<city>/*.json).

For each corner it takes the best low-cost fix the evidence supports without a site visit (brief.SUPPORTED: measured in
this city, the record FHWA cites, or the median of national studies whose conditions the record shows), and keeps
apart the larger "textbook" estimate that would need a site check or that the city's own record contradicts. One fix
per corner, never added together at a corner (the Highway Safety Manual's simple method does not allow stacking).

The worst corners improve partly on their own (regression to the mean). The plan measures that from the cases' own
crash counts: the corners with the most crashes in the first two full years, and no recorded project in the four
years, against all such corners, two years later. The avoidable totals are shown with and without that correction.

Every headline number the README, the site and the letters use comes from `build`, and each agency's letter is
checked by the same number checker as the engineer's claims (context.FactCheck)."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from . import brief, context, harm, opendata
from .config import SETTINGS, asof, portable
from .evaluate import RESULTS_DIR

BEFORE, AFTER = ("2022", "2023"), ("2024", "2025")  # full calendar years inside every case's five-year window
TOP_SHARE = 0.25  # "the worst corners" for the regression-to-the-mean measurement
TIER_WORDS = {"measured here": "this city's own past installs, which passed the causal gate (a stricter calibrated "
                                "check is less sure); the estimate uses the national CMF, the smaller effect",
              "FHWA-cited": "the study FHWA's fact sheet cites", "national studies": "national studies"}


def cases(city: str, runs_dir: Path | None = None, refresh: bool = True) -> list[dict]:
    """The city's saved cases, rewritten by the current code (claims, fixes, owners) unless refresh=False."""
    from . import engineer
    src = (runs_dir or SETTINGS.runs_dir) / "engineer" / city
    out = []
    for p in sorted(src.glob("*.json")):
        r = json.loads(p.read_text())
        out.append({**(engineer.refresh(r) if refresh else r), "_slug": p.stem})
    return out


def _fix(o: dict | None) -> dict | None:
    if not o:
        return None
    return {"countermeasure": o["countermeasure"], "cmf_id": o["cmf_id"], "evidence": o.get("evidence"),
            "crashes_avoided_per_year": o["expected_crashes_avoided_per_year"],
            "harm_avoided_usd_per_year": o["harm_avoided_usd_per_year"],
            "pays_for_itself_under_usd": o["break_even_cost_usd"], "verify_on_site": o.get("verify_on_site")}


def corner(r: dict) -> dict:
    """One corner's row: its harm, its best supported low-cost fix, the largest low-cost estimate of any tier, owners,
    and the flags the plan counts."""
    f = r["findings"]
    fx, tp, who, rc = f["choose_fixes"], f["test_programs"], f["who_must_act"], f.get("root_cause") or {}
    low = [o for o in fx.get("options", []) if o.get("scale") == "low-cost"]
    for o in low:
        o.setdefault("evidence", brief.evidence_tier(o))
    best = next((o for o in low if o["evidence"] in brief.SUPPORTED), None)
    textbook = max(low, key=lambda o: o["expected_crashes_avoided_per_year"], default=None)
    h = fx.get("harm") or {}
    owners = [{"party": o["party"], "confidence": o["confidence"],
               "presumed": o["confidence"] == "inferred" and str((o.get("basis") or {}).get("value") or "").startswith("no ")}
              for o in who.get("owners", [])]
    years = [p.get("year") for p in tp.get("projects_here") or []]
    return {"slug": r.get("_slug") or engineer_slug(r["junction"]["name"]),
            "name": r["junction"]["name"].split(",")[0], "lat": r["junction"].get("lat"), "lon": r["junction"].get("lon"),
            "injury_crashes": (fx.get("crashes") or {}).get("injury_crashes"),
            "injury_crashes_per_year": h.get("injury_crashes_per_year"), "harm_usd_per_year": h.get("usd_per_year"),
            "best": _fix(best), "textbook": _fix(textbook), "owners": owners,
            "requesters": [q["party"] for q in who.get("requesters", [])],
            "repeat_risk": [x["program"] for x in tp.get("repeat_risk") or []],
            "has_pattern": bool(rc.get("over_represented")),
            "by_year": (fx.get("crashes") or {}).get("by_year") or {},
            "project_years": sorted(y for y in years if isinstance(y, int))}


def engineer_slug(name: str) -> str:
    from . import engineer
    return engineer.slug(name)


def regression_to_mean(rows: list[dict]) -> dict:
    """How much the worst corners' crash counts fall on their own: corners with no recorded project in the four years,
    the top TOP_SHARE by crashes in BEFORE, their AFTER / BEFORE ratio over that of all such corners. A factor below 1
    is the share of a worst corner's count expected to persist."""
    lo, hi = int(BEFORE[0]), int(AFTER[-1])
    ok = [r for r in rows if not any(lo <= y <= hi for y in r["project_years"])
          and all(y in r["by_year"] for y in BEFORE + AFTER)]
    if len(ok) < 8:
        return {"factor": None, "corners": len(ok), "note": "too few corners without a project to measure"}
    b = {id(r): sum(r["by_year"][y] for y in BEFORE) for r in ok}
    a = {id(r): sum(r["by_year"][y] for y in AFTER) for r in ok}
    top = sorted(ok, key=lambda r: b[id(r)], reverse=True)[:max(2, int(TOP_SHARE * len(ok)))]
    ratio = lambda rs: sum(a[id(r)] for r in rs) / max(sum(b[id(r)] for r in rs), 1)
    factor = min(1.0, ratio(top) / max(ratio(ok), 1e-9))
    import random
    rng, boots = random.Random(7), []
    for _ in range(1000):  # bootstrap over corners: the selection of the worst quarter is redone in each resample
        s = [rng.choice(ok) for _ in ok]
        t = sorted(s, key=lambda r: b[id(r)], reverse=True)[:max(2, int(TOP_SHARE * len(s)))]
        boots.append(min(1.0, ratio(t) / max(ratio(s), 1e-9)))
    boots.sort()
    return {"factor": round(factor, 3), "factor_ci95": [round(boots[24], 3), round(boots[974], 3)],
            "corners": len(ok), "top": len(top), "years_before": list(BEFORE),
            "years_after": list(AFTER), "top_ratio": round(ratio(top), 3), "all_ratio": round(ratio(ok), 3)}


def summarize(rows: list[dict], rtm: dict, distinct: dict | None) -> dict:
    sup = [r for r in rows if r["best"]]
    avoided = sum(r["best"]["crashes_avoided_per_year"] for r in sup)
    usd = sum(r["best"]["harm_avoided_usd_per_year"] for r in sup)
    text = sum(r["textbook"]["crashes_avoided_per_year"] for r in rows if r["textbook"])
    f = rtm.get("factor") or 1.0  # no measurable factor (too few corners without a project): shown uncorrected
    # totals add corners, so a crash near two corners counts twice; scale by the city's distinct share of crashes
    once = ((distinct or {}).get("injury_crashes_distinct") or 0) / max(sum(r["injury_crashes"] or 0 for r in rows), 1)
    once = min(once, 1.0) if once else 1.0
    by_tier: dict[str, int] = {}
    for r in sup:
        by_tier[r["best"]["evidence"]] = by_tier.get(r["best"]["evidence"], 0) + 1
    unsupported = sum(1 for r in rows if r["textbook"] and (not r["best"] or r["textbook"]["countermeasure"] != r["best"]["countermeasure"]))
    city_dot = {r_["party"] for r in rows for r_ in r["owners"] if r_["confidence"] != "recorded" or "city" in r_["party"].lower()}
    others = [r for r in rows if any(o["confidence"] == "recorded" and o["party"] not in city_dot for o in r["owners"])]
    repeat: dict[str, int] = {}
    for r in rows:
        for p in r["repeat_risk"]:
            repeat[p] = repeat.get(p, 0) + 1
    return {"corners": len(rows),
            "injury_crashes_total": int(sum(r["injury_crashes"] or 0 for r in rows)),
            "harm_usd_per_year_summed": round(sum(r["harm_usd_per_year"] or 0 for r in rows), -5),
            "harm_usd_per_year": (distinct or {}).get("harm_usd_per_year"),
            "injury_crashes_distinct": (distinct or {}).get("injury_crashes_distinct"),
            "corners_with_supported_fix": len(sup), "supported_by_tier": by_tier,
            "crashes_avoided_per_year_total": round(avoided, 1),
            "crashes_avoided_per_year_after_rtm": round(avoided * f, 1),
            "distinct_share": round(once, 3),
            "crashes_avoided_per_year_counted_once": round(avoided * once, 1),
            "crashes_avoided_per_year_counted_once_after_rtm": round(avoided * once * f, 1),
            "harm_avoided_usd_per_year_total": round(usd, -5),
            "harm_avoided_usd_per_year_after_rtm": round(usd * f, -5),
            "textbook_crashes_avoided_per_year": round(text, 1),
            "corners_where_textbook_fix_is_not_supported": unsupported,
            "corners_with_another_road_owner": len(others),
            "corners_with_presumed_owner": sum(1 for r in rows if any(o["presumed"] for o in r["owners"])),
            "repeat_risk_corners": repeat, "corners_with_pattern": sum(r["has_pattern"] for r in rows)}


def by_agency(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        for o in r["owners"]:
            g = groups.setdefault(o["party"], {"party": o["party"], "presumed": True, "corners": [], "recorded": 0})
            g["presumed"] = g["presumed"] and (o["presumed"] or o["confidence"] != "recorded")
            g["recorded"] += o["confidence"] == "recorded"
            g["corners"].append(r)
    out = []
    for g in groups.values():
        cs = sorted(g["corners"], key=lambda r: -(r["best"] or {}).get("crashes_avoided_per_year", 0))
        sup = [r for r in cs if r["best"]]
        out.append({"party": g["party"], "presumed": g["presumed"], "corners": [r["slug"] for r in cs],
                    "intersections": len(cs), "intersections_owner_recorded": g["recorded"], "injury_crashes_total": int(sum(r["injury_crashes"] or 0 for r in cs)),
                    "intersections_with_supported_fix": len(sup),
                    "intersections_needing_site_check": sum(1 for r in cs if not r["best"] and r["textbook"]
                                                            and r["textbook"]["evidence"] == "needs a site check"),
                    "crashes_avoided_per_year_total": round(sum(r["best"]["crashes_avoided_per_year"] for r in sup), 1),
                    "harm_avoided_usd_per_year_total": round(sum(r["best"]["harm_avoided_usd_per_year"] for r in sup), -3)})
    return sorted(out, key=lambda g: -g["intersections"])


def _m(usd: float) -> str:
    return f"${usd / 1e6:.1f} million"


def agency_letter(city: str, g: dict, rows: dict[str, dict], records_to: str | None = None) -> dict:
    """A request to one agency for its corners, written by code from the plan's own totals and checked by the number
    checker; the per-corner lines are a table built from the rows."""
    c = opendata.city(city) or {}
    facts = {k: g[k] for k in ("intersections", "intersections_owner_recorded", "injury_crashes_total",
                               "intersections_with_supported_fix",
                               "intersections_needing_site_check", "crashes_avoided_per_year_total",
                               "harm_avoided_usd_per_year_total")}
    facts["years"] = context.YEARS
    facts["records_to"] = records_to or asof().isoformat()
    n, rec = g["intersections"], g["intersections_owner_recorded"]
    whose = ("the road-owner records list you for at least one of the roads" if rec == n else
             "we take you to be responsible for at least one of the roads, because the state's road inventory does not "
             "list them" if rec == 0 else
             f"you are responsible for at least one of the roads (listed in the road-owner records at {rec} of them, "
             "and taken to be yours at the rest because the state's road inventory does not list them)")
    body = (f"In the {facts['years']} years of public police crash records up to {facts['records_to']}, the "
            f"{n} high-crash {'intersection' if n == 1 else 'intersections'} in {c.get('name', city)} where {whose} "
            f"had {g['injury_crashes_total']:,} injury crashes within 100 m (a crash near two of them counts for each). "
            + (f"At {g['intersections_with_supported_fix']} of {'it' if n == 1 else 'them'}, a low-cost fix the evidence supports would avoid "
               f"about {g['crashes_avoided_per_year_total']} crashes a year, worth about "
               f"{_m(g['harm_avoided_usd_per_year_total'])} a year at the U.S. DOT's values. "
               if g["intersections_with_supported_fix"] else
               "None of them has a low-cost fix that the public evidence supports without a site visit. ")
            + (f"At {g['intersections_needing_site_check']} more, a fix needs a site check first; the table names what to "
               "check. " if g["intersections_needing_site_check"] else "")
            + "The table lists each intersection, the fix and the evidence behind it. "
            f"We ask for a safety review at {'the intersection' if n == 1 else 'each intersection'} and for the fixes listed, and a reply on which you will "
            "take up.")
    errors = context.FactCheck(facts).text(body)
    from . import engineer
    errors += engineer.wording(body)
    table = []
    for s in g["corners"]:
        r = rows[s]
        b = r["best"]
        table.append({"intersection": r["name"], "injury_crashes": r["injury_crashes"],
                      "fix": b["countermeasure"] if b else None, "cmf_id": b["cmf_id"] if b else None,
                      "evidence": TIER_WORDS.get(b["evidence"]) if b else "no fix the evidence supports without a site visit",
                      "crashes_avoided_per_year": b["crashes_avoided_per_year"] if b else None,
                      "check_first": (r["textbook"] or {}).get("verify_on_site") if not b else None,
                      "copy_to": "; ".join(r["requesters"])})
    return {"to": g["party"], "subject": f"{g['intersections']} high-crash {'intersection' if g['intersections'] == 1 else 'intersections'} on your roads",
            "body": body if not errors else None, "refused": errors, "facts": facts, "table": table}


def distinct_totals(city: str) -> dict | None:
    p = RESULTS_DIR / "bench" / f"citywide_{city}.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text())["summary"]
    return {k: s.get(k) for k in ("harm_usd_per_year", "injury_crashes_distinct", "since", "killed_distinct")}


def build(city: str, runs_dir: Path | None = None, reports: list[dict] | None = None) -> dict:
    reports = reports if reports is not None else cases(city, runs_dir)
    seen, unique = set(), []
    for r in reports:  # a list can name the same point twice (two screened rows, one place): count it once
        key = (round(r["junction"].get("lat") or 0, 5), round(r["junction"].get("lon") or 0, 5))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    reports = unique
    rows = [corner(r) for r in reports]
    rtm = regression_to_mean(rows)
    dates = sorted({r.get("asof") for r in reports if r.get("asof")})
    records_to = dates[-1] if dates else asof().isoformat()  # the cases' own as-of date, not today
    agencies = by_agency(rows)
    idx = {r["slug"]: r for r in rows}
    c = opendata.city(city) or {}
    try:
        from . import studyrequests
        asked = studyrequests.build(city, reports)
    except FileNotFoundError:  # replay without the downloaded requests
        asked = None
    return {"city": city, "city_name": c.get("name", city), "asof": records_to, "requests": asked,
            "method": __doc__.split("\n\n")[1].replace("\n", " "),
            "caveats": ["Estimates use the Highway Safety Manual's simple method; a qualified engineer must review each fix.",
                        "One fix per corner; totals add corners, so a crash near two corners can count twice.",
                        "The regression-to-the-mean factor is measured within the listed corners, so it is a lower bound "
                        "on that effect where the corners were themselves picked by the same records."],
            "regression_to_mean": rtm, "summary": summarize(rows, rtm, distinct_totals(city)),
            "agencies": [{**g, "letter": agency_letter(city, g, idx, records_to)} for g in agencies],
            "corners": [{k: v for k, v in r.items() if k not in ("by_year",)} for r in rows]}


def to_csv(plan: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["intersection", "injury_crashes", "harm_usd_per_year", "fix", "cmf_id", "evidence",
                "crashes_avoided_per_year", "harm_avoided_usd_per_year", "pays_for_itself_under_usd", "owners",
                "repeat_risk"])
    for r in sorted(plan["corners"], key=lambda r: -(r["harm_usd_per_year"] or 0)):
        b = r["best"] or {}
        w.writerow([r["name"], r["injury_crashes"], r["harm_usd_per_year"], b.get("countermeasure"), b.get("cmf_id"),
                    b.get("evidence"), b.get("crashes_avoided_per_year"), b.get("harm_avoided_usd_per_year"),
                    b.get("pays_for_itself_under_usd"), "; ".join(o["party"] for o in r["owners"]),
                    "; ".join(r["repeat_risk"])])
    return buf.getvalue()


def write(plan: dict) -> Path:
    out = RESULTS_DIR / "bench" / f"plan_{plan['city']}.json"
    out.write_text(portable(json.dumps(plan, indent=1, default=float)))
    return out
