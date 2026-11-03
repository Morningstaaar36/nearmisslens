"""The request letter, from a Junction Safety Brief: short, checked, with its sources added by code.

Two audiences. "agency": to the road owners found by jurisdiction.who_must_act (in the Bronx example, the state DOT
for the expressway and the city DOT for the surface streets), copying the offices that can push for the work.
"resident": to those offices (in New York, the City Council member and the Community Board), asking them to request
the work from the owners.

The offices come from the city's open district boundaries; no person's name is used, so nothing goes stale. A Muse
Spark agent writes the letter from the brief's facts and a checker inside its finish tool rejects any number that is
not in them. The sources are added by code. NearMissLens drafts the letter; it sends nothing."""
from __future__ import annotations

import datetime as dt
import json
import re

from . import context, countermeasures, harm, opendata, panel, treatments
from .config import asof
from .agent import Tool, run_agent
from .config import MODELS


def offices(lat: float, lon: float) -> list[dict]:
    """Who can request the work at this point: the registry's office adapters (district boundaries) that cover it.
    Without any, there is none: the letter never invents an addressee."""
    return opendata.offices_at(lat, lon)


def _plain(name: str) -> str:
    return next((i.get("plain", name) for i in countermeasures.psc_items() if i["name"] == name), name)


def short_agency(party: str) -> str:
    """'the New York State Department of Transportation (NYSDOT), Region 11' -> 'NYSDOT Region 11'."""
    m = re.match(r"(?:the\s+)?.*?\(([^)]+)\),?\s*(.*)$", party)
    return (m.group(1) + (" " + m.group(2) if m.group(2) else "")).strip() if m else re.sub(r"^the\s+", "", party)


def _salutation(parties: list[dict]) -> str:
    """'Dear A and B,' from each addressee's registry salutation; agencies are greeted as colleagues at their short name."""
    if parties and all(p.get("party") and not p.get("salutation") for p in parties):
        # a party's own note ("(route designation only; confirm ownership)") is not part of its name
        names = list(dict.fromkeys(short_agency(re.sub(r"\s*\((?:route|designation|confirm)[^)]*\)", "", p["party"]))
                                   for p in parties))
        return "Dear colleagues at " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]) + ","
    if not parties:
        return "To the road owner (not identified in the city's open records),"
    names = [p.get("salutation") or p.get("party") or p.get("office") for p in parties]
    return "Dear " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]) + ","


def _records(cr: dict, mode: str) -> bool:
    """Whether the crash dataset records injuries for this mode; a summary that does not say is "not recorded"."""
    return mode in ((cr.get("recorded") or {}).get("injured_by_mode") or [])


def facts(brief: dict, offices_: list[dict] | None = None, who: dict | None = None, audience: str = "resident") -> dict:
    """The facts a letter may use, with the figures already rounded the way a letter writes them. who is
    jurisdiction.who_must_act's result: the agency letter goes to its owners and copies its requesters."""
    if offices_ is None:
        offices_ = [{"office": r["party"], "role": r["role"], "source": r["basis"].get("dataset"),
                     **({"contact": r["contact"]} if r.get("contact") else {}),
                     **({"salutation": r["salutation"]} if r.get("salutation") else {})}
                    for r in (who or {}).get("requesters", [])] or offices(brief["dossier"]["lat"], brief["dossier"]["lon"])
    owners = []
    for r in (who or {}).get("owners", []):  # one addressee per agency: a route note on the same agency is merged in
        base = re.sub(r"\s*\((?:route|designation|confirm)[^)]*\)", "", r["party"]).strip()
        same = next((o for o in owners if re.sub(r"\s*\((?:route|designation|confirm)[^)]*\)", "", o["party"]).strip() == base), None)
        if same:
            same["roads"] = sorted(set(same["roads"]) | set(r["roads"]))
            if "(" in same["party"] and "(" not in r["party"].replace(base, ""):
                same.update(party=r["party"], confidence=r["confidence"])
        else:
            owners.append({"party": r["party"], "roads": list(r["roads"]), "confidence": r["confidence"]})
    if audience == "agency" and not owners:
        audience = "resident"  # no recorded owner: the offices that can request the work are the addressees
    d, fx = brief["dossier"], brief.get("fixes") or {}
    cr, pl = d.get("crashes") or {}, d.get("plans") or {}
    killed = context.deaths(cr)
    # the two leading estimated low-cost fixes (reconstructions need a design study first), with their site checks
    supported = [o for o in fx.get("options", []) if o.get("scale", "low-cost") == "low-cost"][:2]
    measured = next((o for o in fx.get("options", []) if o.get("local_evidence")), None)
    h = fx.get("harm") or {}
    done_by = asof().year  # a project dated after the record's date is planned, not done
    dated = sorted((p for p in pl.get("projects", []) if isinstance(p.get("year"), int)), key=lambda p: p["year"])
    projects = [p for p in dated if p["year"] <= done_by]
    planned = [p for p in dated if p["year"] > done_by]
    addressed = owners if audience == "agency" else offices_
    salutation = _salutation(addressed)
    since = dt.date.fromisoformat(cr["since"]) if cr.get("since") else None
    ev = (measured or {}).get("local_evidence") or {}
    return {
        "junction": brief["junction"].split(",")[0], "audience": audience, "addressed_to": addressed,
        "to": "; ".join(o.get("party") or o.get("office") for o in addressed) or "the road owner (not identified in the city's open records)",
        "copy_to": "; ".join(o["office"] for o in offices_) if audience == "agency" else None,
        "salutation": salutation, "road_owners": owners,
        "period": f"the {d.get('years')} years from {since.day} {since:%B %Y}" if since else None,
        "agency": (opendata.city(d.get("city")) or {}).get("agency") or "the city's transportation department",
        "years": d.get("years"), "records_since": cr.get("since"), "crashes": cr.get("crashes"),
        "injury_crashes": cr.get("injury_crashes"),
        # a count the city's dataset does not record is "not recorded", never zero (Seattle records only a total)
        "pedestrians_injured": cr.get("pedestrian_injured", 0) if _records(cr, "pedestrian") else None,
        "cyclists_injured": cr.get("cyclist_injured", 0) if _records(cr, "cyclist") else None,
        "recorded": cr.get("recorded") or {"injured_by_mode": [], "killed": False, "note": "not stated by the dataset"},
        "people_killed": killed,
        "city_priority_location": bool(pl.get("designated")),
        "latest_recorded_safety_project": {k: projects[-1][k] for k in ("name", "year")} if projects else None,
        "planned_safety_project": {k: planned[0][k] for k in ("name", "year")} if planned else None,
        "no_recorded_treatment_in_period": bool(d.get("plan_gap")),
        "harm_million_usd_per_year": round(h["usd_per_year"] / 1e6, 1) if h else None,
        "fixes": [{"name": _plain(o["countermeasure"]), "federal_name": o["countermeasure"],
                   "cmf_id": o["cmf_id"],
                   "crashes_avoided_per_year": o["expected_crashes_avoided_per_year"],
                   "targets": o["targets"], "harm_avoided_usd_per_year": o["harm_avoided_usd_per_year"],
                   "pays_for_itself_under_million_usd": round(o["break_even_cost_usd"] / 1e6, 1),
                   "evidence": o.get("evidence"),
                   "needs_site_check_for": o.get("verify_on_site")} for o in supported],
        "measured_in_this_city": {
            "fix": _plain(measured["countermeasure"]),
            "result": (f"where the city installed it at {ev['sites']:,} intersections, {ev.get('outcome_words', 'injury crashes')} fell "
                       f"{treatments.pct(100 * (1 - ev['theta']))}% (95% interval "
                       f"{treatments.pct(100 * (1 - ev['ci95'][1]))}% to {treatments.pct(100 * (1 - ev['ci95'][0]))}%) "
                       "compared with intersections that got it later"
                       + ("; a stricter check against fake programs is less certain" if ev.get("fake_rank") is not None else "")),
            "needs_site_check_for": measured.get("verify_on_site")} if measured else None,
        "already_in_place": fx.get("in_place", []),
        "tried_here_before": [x["text"] for x in fx.get("repeat_risk") or []],
        "dollar_values": f"the U.S. DOT's official values for the cost of crashes ({harm.BCA['dollar_year']} dollars)",
    }


HEDGE = re.compile(r"\b(check|checked|confirm|confirmed|verify|verified|if|whether|survey|study|assess)\b", re.I)


def condition_errors(text: str, facts: dict) -> list[str]:
    """A fix's site condition ("the current yellow plus all-red is shorter than practice") is something to check on
    site, never a fact about the junction: a sentence that states one must say it is to be checked."""
    conds = [c.strip() for fx in (facts.get("fixes") or []) + [facts.get("measured_in_this_city") or {}]
             for c in (fx.get("needs_site_check_for") or "").split(";") if c.strip()]
    errors = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        low = sent.lower()
        for c in conds:
            words = [w for w in re.findall(r"[a-z]{4,}", c.lower())]
            if words and sum(w in low for w in words) / len(words) >= 0.6 and not HEDGE.search(sent):
                errors.append(f"'{sent.strip()[:90]}' states a site condition as a fact: say it must be checked on site")
                break
    return errors


AGENCY_INSTRUCTIONS = (
    "Write a short, polite, factual letter in plain English (at most 220 words) to the road owners in addressed_to, "
    "asking each for a safety study at the junction and for the fixes listed, on the roads it is responsible for "
    "(road_owners). Start with the salutation given; the To and Cc lines are added for you, so do not repeat them. Say what the official record "
    "shows over the period (crashes, who was hurt, the yearly cost of the harm in the U.S. DOT's official values, "
    "whether any recent safety work is recorded) and what each fix is expected to prevent, using its plain name and "
    "saying what must be checked on site first. If measured_in_this_city is given, quote its result. If "
    "tried_here_before is given, say plainly that the earlier program's effect was not shown and ask for a different "
    "approach. Use only numbers in the facts; write dollar amounts as the facts give them. Do not invent names or "
    "details about the sender: end with the placeholders [Your name] and [Your organisation or address]. Do not add "
    "a list of sources; it is added for you. Call finish with a subject line and the letter body; if it is rejected, "
    "fix the errors.")

INSTRUCTIONS = (
    "Write a short, polite letter in plain English (at most 220 words) from a resident to the offices in "
    "addressed_to, asking them to request a safety study at the junction from the agency and to ask for the fixes "
    "listed. Start with the salutation given. Say what the official record shows over the period (crashes, who was "
    "hurt, the yearly cost of the harm in the U.S. DOT's official values, whether the city recorded any recent safety "
    "work) and what each fix is expected to prevent, using its plain name and saying what must be checked on site first. If measured_in_this_city is given, also ask "
    "them to consider that fix (after a site check of needs_site_check_for, if given) and quote its result. Use only "
    "numbers in the facts; write dollar amounts as the facts give them. Do not invent names, personal stories or "
    "details about the sender: end with the placeholders [Your name] and [Your address]. Do not add a list of "
    "sources; it is added for you. Call finish with a subject line and the letter body; if it is rejected, fix the "
    "errors.")


def sources(brief: dict, f: dict) -> list[str]:
    d = brief["dossier"]
    out = [s for s in ((d.get("crashes") or {}).get("source"), (d.get("plans") or {}).get("source")) if s]
    out += [f"FHWA CMF Clearinghouse, CMF {x['cmf_id']} ({x['name']})" for x in f["fixes"]]
    out.append(harm.SHORT)
    if f.get("measured_in_this_city"):
        out.append("NearMissLens NML-Bench T11: before/after study of the city's own installs (validation/BENCH.md)")
    out += [o["source"] for o in f["addressed_to"] if o.get("source")]
    if f.get("road_owners"):
        out.append("Road owners: the registry's road-inventory layer (see the engineer report's receipts)")
    return list(dict.fromkeys(out))


def draft(client, brief: dict, offices_: list[dict] | None = None, model: str = MODELS["reader"],
          tag: str = "letter", who: dict | None = None, audience: str = "resident") -> dict:
    f = facts(brief, offices_, who, audience)
    check = context.FactCheck(f)
    attempts = []

    def finish(subject: str, body: str) -> dict:
        errors = check.text(subject) + check.text(body) + condition_errors(subject + " " + body, f)
        attempts.append({"subject": subject, "body": body, "errors": errors})
        return {"error": "rejected by the fact checker", "errors": errors} if errors else {"ok": True}

    tool = Tool("finish", "Submit the letter.", panel._obj({"subject": {"type": "string"}, "body": {"type": "string"}},
                                                           ["subject", "body"]), finish)
    instructions = AGENCY_INSTRUCTIONS if f["audience"] == "agency" else INSTRUCTIONS
    run = run_agent(client, model, instructions, "Facts:\n" + json.dumps(f, default=str), [tool], 6, 0.03,
                    effort="low", tag=tag, escalate_after=3)
    final = next((a for a in reversed(attempts) if not a["errors"]), None)
    text = None
    if final:
        cc = f"\nCc: {f['copy_to']}" if f.get("copy_to") else ""
        text = (f"To: {f['to']}{cc}\nSubject: {final['subject']}\n\n{final['body'].strip()}\n\nSources:\n"
                + "\n".join(f"- {s}" for s in sources(brief, f))
                + f"\n\n(Drafted with NearMissLens from public records as of {asof().isoformat()}. Review it "
                  "and send it yourself; NearMissLens sends nothing.)")
    return {"letter": text, "to": f["addressed_to"], "facts": f, "attempts": len(attempts),
            "checker_errors": [] if final else (attempts[-1]["errors"] if attempts else ["no letter"]),
            "rejected_drafts": sum(bool(a["errors"]) for a in attempts), "usd": round(run.usd, 5),
            "stopped": run.stopped}
