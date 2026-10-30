"""A letter a resident can send: from a Junction Safety Brief to a short, checked letter asking the people who can
request the work (in New York, the City Council member and the Community Board for the junction) to ask the city's
transportation department for a safety study and the ranked fixes.

The offices come from the city's open district boundaries; no person's name is used, so nothing goes stale. A Muse
Spark agent writes the letter from the brief's facts and a checker inside its finish tool rejects any number that is
not in them. The sources are added by code. NearMissLens drafts the letter; it sends nothing."""
from __future__ import annotations

import datetime as dt
import json

from . import context, panel
from .agent import Tool, run_agent

BOROUGHS = {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}
PLAIN = {  # how a resident would name each FHWA Proven Safety Countermeasure
    "Medians and Pedestrian Refuge Islands in Urban and Suburban Areas": "pedestrian refuge islands",
    "Leading Pedestrian Interval": "a leading pedestrian interval (a walk signal a few seconds before the green)",
    "Crosswalk Visibility Enhancements": "high-visibility crosswalks",
    "Dedicated Left- and Right-Turn Lanes at Intersections": "dedicated turn lanes",
    "Reduced Left-Turn Conflict Intersections": "a redesign that removes risky left turns",
    "Backplates with Retroreflective Borders": "reflective backplates on the traffic signals",
    "Yellow Change Intervals": "longer yellow signal times",
    "Pedestrian Hybrid Beacons": "a pedestrian hybrid beacon",
    "Rectangular Rapid Flashing Beacons": "flashing beacons at the crosswalk",
    "Walkways": "a continuous sidewalk", "Lighting": "better street lighting", "Roundabouts": "a roundabout"}
AGENCY = {"nyc": "the NYC Department of Transportation (NYC DOT)"}


def _socrata_at(endpoint: str, field: str, lat: float, lon: float) -> str | None:
    js, _ = context.fetch(endpoint, {"$select": field, "$where": f"intersects(the_geom,'POINT ({lon} {lat})')"})
    return str(js[0][field]) if isinstance(js, list) and js and js[0].get(field) else None


def offices(lat: float, lon: float, city: str | None) -> list[dict]:
    """Who can request the work at this point. New York: the City Council district and the Community Board, from
    NYC Open Data's district boundaries (872g-cjhh, 5crt-au7u)."""
    if city != "nyc":
        return [{"office": "your city council member", "source": None}]
    out = []
    cd = _socrata_at("https://data.cityofnewyork.us/resource/872g-cjhh.json", "coundist", lat, lon)
    if cd:
        out.append({"office": f"Council Member, District {int(cd)}, New York City Council", "district": int(cd),
                    "contact": f"https://council.nyc.gov/district-{int(cd)}/",
                    "source": "NYC Open Data, City Council Districts (872g-cjhh)"})
    bc = _socrata_at("https://data.cityofnewyork.us/resource/5crt-au7u.json", "boro_cd", lat, lon)
    if bc and int(bc) % 100 <= 18:  # higher numbers are joint interest areas such as large parks, without a board
        out.append({"office": f"{BOROUGHS[int(bc) // 100]} Community Board {int(bc) % 100}",
                    "board": int(bc) % 100, "source": "NYC Open Data, Community Districts (5crt-au7u)"})
    return out


def facts(brief: dict, offices_: list[dict]) -> dict:
    """The facts a letter may use, with the figures already rounded the way a letter writes them."""
    d, fx = brief["dossier"], brief.get("fixes") or {}
    cr, pl = d.get("crashes") or {}, d.get("plans") or {}
    killed = sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed"))
    supported = [o for o in fx.get("options", []) if not o.get("verify_on_site")][:2]
    measured = next((o for o in fx.get("options", []) if o.get("local_evidence")), None)
    h = fx.get("harm") or {}
    projects = sorted((p for p in pl.get("projects", []) if isinstance(p.get("year"), int)), key=lambda p: p["year"])
    council = any("Council Member" in o["office"] for o in offices_)
    boards = [o["office"] for o in offices_ if "Community Board" in o["office"]]
    salutation = ("Dear Council Member" + (f" and members of {boards[0]}" if boards else "") + ",") if council \
        else "Dear " + (offices_[0]["office"] if offices_ else "Council Member") + ","
    since = dt.date.fromisoformat(cr["since"]) if cr.get("since") else None
    ev = (measured or {}).get("local_evidence") or {}
    return {
        "junction": brief["junction"].split(",")[0], "addressed_to": offices_, "salutation": salutation,
        "period": f"the {d.get('years')} years from {since.day} {since:%B %Y}" if since else None,
        "agency": AGENCY.get(d.get("city"), "the city's transportation department"),
        "years": d.get("years"), "records_since": cr.get("since"), "crashes": cr.get("crashes"),
        "injury_crashes": cr.get("injury_crashes"),
        "pedestrians_injured": cr.get("pedestrian_injured", 0), "cyclists_injured": cr.get("cyclist_injured", 0),
        "people_killed": killed,
        "city_priority_location": bool(pl.get("designated")),
        "latest_recorded_safety_project": {k: projects[-1][k] for k in ("name", "year")} if projects else None,
        "no_recorded_treatment_in_period": bool(d.get("plan_gap")),
        "harm_million_usd_per_year": round(h["usd_per_year"] / 1e6, 1) if h else None,
        "fixes": [{"name": PLAIN.get(o["countermeasure"], o["countermeasure"]), "federal_name": o["countermeasure"],
                   "cmf_id": o["cmf_id"],
                   "crashes_avoided_per_year": o["expected_crashes_avoided_per_year"],
                   "targets": o["targets"], "harm_avoided_usd_per_year": o["harm_avoided_usd_per_year"],
                   "pays_for_itself_under_million_usd": round(o["break_even_cost_usd"] / 1e6, 1)} for o in supported],
        "measured_in_this_city": {
            "fix": PLAIN.get(measured["countermeasure"], measured["countermeasure"]),
            "result": (f"where the city installed it at {ev['sites']:,} intersections, pedestrian injury crashes fell "
                       f"{round(100 * (1 - ev['theta']))}% (95% interval {round(100 * (1 - ev['ci95'][1]))}% to "
                       f"{round(100 * (1 - ev['ci95'][0]))}%) compared with intersections that got it later"),
            "needs_site_check_for": measured.get("verify_on_site")} if measured else None,
        "already_in_place": fx.get("in_place", []),
        "dollar_values": "the U.S. DOT's official values for the cost of crashes (2024 dollars)",
    }


INSTRUCTIONS = (
    "Write a short, polite letter in plain English (at most 220 words) from a resident to the offices in "
    "addressed_to, asking them to request a safety study at the junction from the agency and to ask for the fixes "
    "listed. Start with the salutation given. Say what the official record shows over the period (crashes, who was "
    "hurt, the yearly cost of the harm in the U.S. DOT's official values, whether the city recorded any recent safety "
    "work) and what each fix is expected to prevent, using its plain name. If measured_in_this_city is given, also ask "
    "them to consider that fix (after a site check of needs_site_check_for, if given) and quote its result. Use only "
    "numbers in the facts; write dollar amounts as the facts give them. Do not invent names, personal stories or "
    "details about the sender: end with the placeholders [Your name] and [Your address]. Do not add a list of "
    "sources; it is added for you. Call finish with a subject line and the letter body; if it is rejected, fix the "
    "errors.")


def sources(brief: dict, f: dict) -> list[str]:
    d = brief["dossier"]
    out = [s for s in ((d.get("crashes") or {}).get("source"), (d.get("plans") or {}).get("source")) if s]
    out += [f"FHWA CMF Clearinghouse, CMF {x['cmf_id']} ({x['name']})" for x in f["fixes"]]
    out.append("U.S. DOT Benefit-Cost Analysis Guidance, 2026 Update, Table A-1 (2024 dollars)")
    if f.get("measured_in_this_city"):
        out.append("NearMissLens NML-Bench T11: before/after study of the city's own installs (validation/BENCH.md)")
    out += [o["source"] for o in f["addressed_to"] if o.get("source")]
    return out


def draft(client, brief: dict, offices_: list[dict], model: str = "muse-spark-1.3-contributor",
          tag: str = "letter") -> dict:
    f = facts(brief, offices_)
    check = context.FactCheck(f)
    attempts = []

    def finish(subject: str, body: str) -> dict:
        errors = check.text(subject) + check.text(body)
        attempts.append({"subject": subject, "body": body, "errors": errors})
        return {"error": "rejected by the fact checker", "errors": errors} if errors else {"ok": True}

    tool = Tool("finish", "Submit the letter.", panel._obj({"subject": {"type": "string"}, "body": {"type": "string"}},
                                                           ["subject", "body"]), finish)
    run = run_agent(client, model, INSTRUCTIONS, "Facts:\n" + json.dumps(f, default=str), [tool], 6, 0.03,
                    effort="low", tag=tag, escalate_after=3)
    final = next((a for a in reversed(attempts) if not a["errors"]), None)
    to = "; ".join(o["office"] for o in offices_)
    text = None
    if final:
        text = (f"To: {to}\nSubject: {final['subject']}\n\n{final['body'].strip()}\n\nSources:\n"
                + "\n".join(f"- {s}" for s in sources(brief, f))
                + f"\n\n(Drafted with NearMissLens on {dt.date.today().isoformat()} from public records. Review it "
                  "and send it yourself; NearMissLens sends nothing.)")
    return {"letter": text, "to": offices_, "facts": f, "attempts": len(attempts),
            "checker_errors": [] if final else (attempts[-1]["errors"] if attempts else ["no letter"]),
            "rejected_drafts": sum(bool(a["errors"]) for a in attempts), "usd": round(run.usd, 5),
            "stopped": run.stopped}
