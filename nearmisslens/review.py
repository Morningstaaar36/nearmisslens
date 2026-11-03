"""Before you commit: a pre-commitment review of a proposed street-safety project, for the engineer or directorate
that must decide whether to fund it.

Give it a proposal in plain words ("Leading pedestrian intervals at Street A & Street B, about $15,000").
The work a team would do before committing is done by agents, and every step is refereed by code:

1. Muse Spark (the orchestrator) registers the proposal: the place, which federal Proven Safety Countermeasure it
   is (a closed list, so a fix is never invented), the cost and the goal.
2. The checked tools build the corner's case: police crash record, what the crashes have in common, the city's own
   past programs through the causal gate, every countermeasure the evidence supports here, the road owner.
3. Code appraises the proposal against that case: does the record show the crashes this fix targets, how many a
   year it is expected to avoid, what that is worth against its cost, how strong the evidence is, what must be true
   on site, and whether another fix is expected to do much more. **Code sets the verdict**; the model cannot.
4. A red team on another model family (Muse Spark Open on Baseten) writes the pre-mortem: the strongest reasons the
   project could be the wrong call. Each objection must point at a field of a receipt and state its value; code keeps
   only the objections whose facts check out, so an objection is evidence, not opinion.
5. Muse Spark writes the decision memo. The gate refuses it unless the verdict is the code's, every number is in the
   receipt the finding cites, and every kept objection is answered. A work order to the road owner can be drafted.

Nothing here knows a particular city, corner or project; the registry and the input bring them."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from . import countermeasures, engineer, orchestrator
from .agent import Tool, run_agent
from .brief import SUPPORTED, same_corner  # noqa: F401 (used below)
from .config import MODELS, SETTINGS, portable
from .config import asof as config_asof

MAX_INPUT = 1500
EXAMPLES = Path(__file__).resolve().parent.parent / "validation" / "examples" / "proposals.json"


def example(n: int) -> dict:
    """A real proposal from the test set (validation/examples/proposals.json), numbered from 1."""
    rows = json.loads(EXAMPLES.read_text())["proposals"] if EXAMPLES.exists() else []
    if not 1 <= n <= len(rows):
        raise ValueError(f"there are {len(rows)} saved proposals")
    return rows[n - 1]
RED_TEAM_BUDGET_USD = 0.05
MAX_OBJECTIONS = 5
ALTERNATIVE_FACTOR = 2.0  # another supported fix "does much more" when it avoids at least this multiple of the crashes

VERDICTS = {
    "proceed": "proceed: the evidence supports this fix here",
    "proceed_after_site_check": "proceed only after a site check confirms what the estimate assumes",
    "compare_alternative": "compare before committing: another supported fix is expected to avoid much more",
    "outside_evidence": "not covered by the evidence: no crash-modification study fits this fix at this site, so the "
                        "decision rests on a site study and an engineer's assessment, not on this record",
    "reconsider": "reconsider: the record or the evidence does not support this fix here as proposed",
    "mixed": "decide part by part: the parts of this proposal get different verdicts",
}
CAUTION = ("reconsider", "outside_evidence", "proceed_after_site_check", "compare_alternative", "proceed")
COST_COVERS = ("this fix only", "a package with other work", "not stated")


def _no_target_crashes(reason: str | None) -> bool:
    """Whether a fix was left unestimated only because the record shows none of the crashes it targets (each of
    countermeasures.select's reasons then reads "the record has no ..."), rather than because no study fits the site."""
    parts = [x.strip() for x in (reason or "").split(";") if x.strip()]
    return bool(parts) and all(x.startswith("the record has no ") for x in parts)


def site_fixes() -> list[str]:
    """The federal Proven Safety Countermeasures that are built at a site (not plans or audits)."""
    return [i["name"] for i in countermeasures.psc_items() if i.get("site_fix") is not False]


def _avoided(o: dict) -> float:
    return float(o.get("injury_crashes_avoided_per_year") or 0.0)


def appraise(fx: dict, countermeasure: str, cost_usd: float | None) -> dict:
    """The proposal against the corner's evidence (choose_fixes' data), and the verdict by rule. Pure: no model."""
    opts = fx.get("options") or []
    me = next((o for o in opts if o["countermeasure"] == countermeasure), None)
    unq = next((o for o in fx.get("not_estimated") or [] if o["countermeasure"] == countermeasure), None)
    placed = next((p for p in fx.get("in_place") or [] if p.get("countermeasure") == countermeasure), None)
    supported = [o for o in opts if o["countermeasure"] != countermeasure and o.get("evidence") in SUPPORTED]
    best = max(supported, key=_avoided, default=None)
    keep = ("countermeasure", "scale", "evidence", "cmf", "crf_pct", "targets", "target_crashes_per_year",
            "expected_crashes_avoided_per_year", "injury_crashes_avoided_per_year", "harm_avoided_usd_per_year",
            "break_even_cost_usd", "verify_on_site", "local_evidence", "local_program")
    out = {"countermeasure": countermeasure, "cost_usd": cost_usd,
           "proposed": {k: me.get(k) for k in keep if me.get(k) is not None} if me else None,
           "best_alternative": {k: best.get(k) for k in keep if best.get(k) is not None} if best else None,
           "in_place": placed, "not_estimated_reason": (unq or {}).get("reason"),
           "site_control": fx.get("control"), "reasons": []}
    why = out["reasons"]
    if placed:
        verdict = "reconsider"
        why.append(f"the city's records show {countermeasure} already installed here"
                   + (f" ({placed['year']})" if placed.get("year") else ""))
    elif me is None and unq and _no_target_crashes(unq.get("reason")):
        verdict = "reconsider"
        why.append(f"the record shows none of the crashes {countermeasure} targets: {unq['reason']}")
    elif me is None:
        verdict = "outside_evidence"  # absence of a fitting study is not evidence against the fix
        why.append(f"no crash-modification evidence for {countermeasure} applies to this site as the record shows it"
                   + (f": {unq['reason']}" if unq and unq.get("reason") else ""))
    elif not me.get("target_crashes_per_year"):
        verdict = "reconsider"
        why.append(f"the record shows none of the crashes {countermeasure} targets ({me.get('targets')})")
    elif me.get("evidence") == "contradicted here":
        verdict = "reconsider"
        why.append("this city's own past installations, tested against the record, rule out the national effect")
    elif me.get("evidence") == "needs a site check":
        verdict = "proceed_after_site_check"
        why.append(f"the estimate holds only if the site shows: {me.get('verify_on_site')}")
    elif cost_usd and me.get("break_even_cost_usd") is not None and cost_usd > me["break_even_cost_usd"]:
        verdict = "reconsider"
        why.append(f"the stated cost (${cost_usd:,.0f}) is above what the harm it is expected to avoid is worth over its "
                   f"life (${me['break_even_cost_usd']:,.0f})")
    elif best and _avoided(best) >= ALTERNATIVE_FACTOR * _avoided(me) and _avoided(best) > _avoided(me):
        verdict = "compare_alternative"
        why.append(f"{best['countermeasure']} is expected to avoid {_avoided(best):g} injury crashes a year here, against "
                   f"{_avoided(me):g} for the proposal"
                   + (f" (it targets {best.get('targets')} crashes; the proposal targets {me.get('targets')} crashes, "
                      "so both may be worth doing)" if best.get("targets") != me.get("targets") else ""))
    else:
        verdict = "proceed"
        why.append(f"the record shows the crashes it targets and the evidence is {me.get('evidence')}")
    if me and cost_usd and me.get("break_even_cost_usd"):
        out["benefit_cost_ratio"] = round(me["break_even_cost_usd"] / cost_usd, 1)
    out["verdict"], out["verdict_text"] = verdict, VERDICTS[verdict]
    return out


def implied_control(countermeasure: str) -> str | None:
    """The traffic control a countermeasure is built for (its PSC entry), or None for any control."""
    item = next((i for i in countermeasures.psc_items() if i["name"] == countermeasure), None)
    c = (item or {}).get("site_control")
    return None if c in (None, "any") else c


def appraise_proposal(fx: dict, parts: list[dict], cost_usd: float | None, cost_covers: str,
                      fx_for_control=None) -> dict:
    """Every part of a proposal against the corner's evidence, each with a verdict by rule, and the proposal's.
    A part built for another control than the map shows (beacons at a mapped signal, a signal phase where none is
    mapped) is estimated as the proposal describes the site (fx_for_control), and must have the control confirmed
    on site first: a signal within the mapping radius may belong to a nearby crossing. The stated cost is compared
    with a fix's benefit only when it pays for that fix alone. Pure: fx_for_control(control) -> fix options."""
    mapped = fx.get("control")
    one = len(parts) == 1 and cost_covers == "this fix only"
    rows = []
    for part in parts:
        cm = part["countermeasure"]
        if cm == "other":
            rows.append({"countermeasure": "other", "what": part.get("what"), "verdict": "outside_evidence",
                         "verdict_text": VERDICTS["outside_evidence"],
                         "reasons": [f"{part.get('what') or 'this part'} is not one of the federal Proven Safety "
                                     "Countermeasures, so no crash-modification evidence is applied to it here; it needs "
                                     "its own study"]})
            continue
        need = implied_control(cm)
        conflict = bool(need and mapped and mapped != "unknown" and need != mapped and fx_for_control)
        a = appraise(fx_for_control(need) if conflict else fx, cm, cost_usd if one else None)
        a["what"] = part.get("what")
        if conflict:
            a["control_check"] = {"proposal_implies": need, "mapped": mapped,
                                  "basis": "OpenStreetMap: traffic signals and stop signs mapped within 80 m"}
            if a["verdict"] in ("proceed", "compare_alternative"):
                a["verdict"], a["verdict_text"] = "proceed_after_site_check", VERDICTS["proceed_after_site_check"]
            a["reasons"].insert(0, f"{cm} is built for {need.lower()} crossings, and the map shows the corner as "
                                   f"{mapped.lower()} (a signal or stop within 80 m may belong to a nearby crossing): "
                                   f"confirm the control on site; the estimate here is for a {need.lower()} site")
        rows.append(a)
    verdicts = {r["verdict"] for r in rows}
    verdict = rows[0]["verdict"] if len(verdicts) == 1 else "mixed"
    out = {"parts": rows, "verdict": verdict, "verdict_text": VERDICTS[verdict], "site_control": mapped,
           "cost_usd": cost_usd, "cost_covers": cost_covers,
           "reasons": [f"{r['countermeasure'] if r['countermeasure'] != 'other' else r.get('what')}: {r['verdict_text']} "
                       f"({'; '.join(r['reasons'])})" for r in rows] if len(rows) > 1 else list(rows[0]["reasons"])}
    if cost_usd and not one:
        out["reasons"].append(f"the stated cost (${cost_usd:,.0f}) pays for "
                              f"{'several parts' if len(parts) > 1 else 'more than this fix'}"
                              f"{'' if cost_covers != 'not stated' else ' or is not said to be for this fix alone'}, "
                              "so it is not compared with one fix's benefit")
    first = rows[0]
    for k in ("proposed", "best_alternative", "in_place", "not_estimated_reason", "benefit_cost_ratio", "countermeasure"):
        if k in first:
            out[k] = first[k]  # the first part's numbers, where a single-fix reader looks for them
    return out


INSTRUCTIONS = """You review a proposed street-safety project before an agency commits money to it. You are the
analyst; code referees every step. Work in this order:
1. register_proposal: the intersection ("Street A & Street B, City"); every part of the proposal, each as the
   federal countermeasure it is (choose from the list; "other" with a short description if none fits; never drop a
   part); the cost in dollars if the proposal states one (0 if not) and what that cost pays for; the goal in its own
   words.
2. investigate the intersection (draft_letter true: a work order to the road owner).
3. appraise: code tests each part against the corner's evidence and sets each verdict and the proposal's.
4. program_record for the countermeasure, if the city may have run it as a program.
5. red_team: an independent model argues against the decision; code keeps only objections whose facts check out.
6. check_memo, fix what it names, then finish.
The memo: a summary of two or three sentences that states the verdict (and each part's), the parts with their
verdicts exactly as appraised, findings that each cite the D receipt holding
their numbers (crashes, what they have in common, the expected effect and its evidence, cost against benefit, the
best alternative, the road owner), and an answer to every kept objection, citing a receipt. Never state a number that
is not in the receipt you cite, never claim a fix will prevent a crash for certain, and never change the verdict."""


class Review:
    def __init__(self, city: str):
        self.desk = orchestrator.Desk(city)
        self.proposal: dict | None = None
        self.appraisal: dict | None = None
        self.objections: list[dict] | None = None
        self.final: dict | None = None
        self.red_team_usd = 0.0
        self.dropped: list[dict] = []  # red-team objections code did not keep, with why
        self.off_corner: str | None = None
        self.outside: str | None = None  # why the proposal is outside the city's limits, when it is
        self.lat_lon: tuple[float, float] | None = None


def _last_refusal(run) -> str | None:
    """The last tool refusal of a run that did not publish, so an abstention says why."""
    for s in reversed(run.steps):
        r = s.result if isinstance(s.result, dict) else {}
        if r.get("error") and s.tool != "red_team":
            return f"not published; the last refusal: {str(r['error'])[:300]}"
    return None


def _receipt_of(desk, tool: str) -> tuple[str, dict] | None:
    return next(((rid, r["data"]) for rid, r in desk.receipts.items() if r["tool"] == tool), None)


def _compact(desk) -> dict:
    """What the red team reads: each receipt's data, trimmed but with its structure kept, so a field path it cites
    points at the same value in the full receipt."""
    out = {}
    for rid, r in desk.receipts.items():
        d = r["data"]
        if r["tool"] == "choose_fixes" and isinstance(d, dict):
            d = {"crashes": {k: v for k, v in (d.get("crashes") or {}).items() if isinstance(v, (int, float, str))},
                 "options": [{k: o.get(k) for k in ("countermeasure", "evidence", "targets", "target_crashes_per_year",
                                                    "injury_crashes_avoided_per_year", "break_even_cost_usd",
                                                    "verify_on_site")} for o in (d.get("options") or [])[:8]],
                 "control": d.get("control")}
        elif isinstance(d, dict):
            d = {k: v for k, v in d.items() if isinstance(v, (int, float, str, bool)) or k in
                 ("proposed", "best_alternative", "reasons", "over_represented", "owners")}
        out[rid] = {"tool": r["tool"], "data": d}
    return out


RESTATES = re.compile(r"(^|\.)(verdict|verdict_text|reasons?)(\.|$)")


def facts(compact: dict, limit: int = 120) -> list[dict]:
    """Every single value in the red team's receipts as (receipt, field path, value): the objections cite these
    exactly, so a fact is never lost to a mistyped path. The appraisal's own verdict and reasons are left out: an
    objection resting on them only restates the decision."""
    out = []

    def walk(rid, d, path):
        if len(out) >= limit:
            return
        if isinstance(d, dict):
            for k, v in d.items():
                walk(rid, v, f"{path}.{k}" if path else str(k))
        elif isinstance(d, list):
            for i, v in enumerate(d[:8]):
                walk(rid, v, f"{path}.{i}" if path else str(i))
        elif d is not None and d != "" and not RESTATES.search(path):
            out.append({"receipt": rid, "field": path, "value": d if not isinstance(d, str) else d[:160]})
    for rid, r in compact.items():
        if r["tool"] != "red_team":
            walk(rid, r["data"], "")
    return out


def _as_number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", "").replace("$", "").rstrip("%"))
    except ValueError:
        return None


def _matches(found, value) -> bool:
    """Whether the receipt's value is the one the objection states: a number equal within 1% (so "1" never matches
    100), text equal or a whole phrase of it (case aside); a list or object matches only as its exact JSON."""
    if isinstance(found, (list, dict)):
        return json.dumps(found, sort_keys=True, default=str) == str(value)
    a, b = _as_number(found), _as_number(value)
    if a is not None or b is not None:
        return a is not None and b is not None and abs(a - b) <= max(0.01 * abs(a), 0.005)
    fs, vs = str(found).strip().lower(), str(value).strip().lower()
    return bool(vs) and len(vs) >= 3 and (vs == fs or re.search(r"(?<!\w)" + re.escape(vs) + r"(?!\w)", fs) is not None)


RED_TEAM = """You are the red team for a street-safety project an agency is deciding on. Read the proposal, the code's
appraisal (its verdict, and each part's) and the receipts, and argue AGAINST the verdict: if it says proceed, the
strongest reasons proceeding could be wrong (wrong target crashes, weak evidence, a precondition the site may not
meet, a better alternative, cost against benefit, crashes the fix does not touch, a road owner who must agree); if it
says reconsider or not covered by the evidence, the strongest reasons the agency might still be right to fund it
(serious harm the record shows, crashes the fix does target, what the evidence cannot see). Do not restate the
verdict or agree with it: an objection that supports the verdict is useless.
Each objection must rest on one fact from the "facts" list: copy its receipt, field and value exactly (the
receipts are there for context). An objection about the verdict or its reasons themselves is not a fact and is
dropped. Code checks each fact and keeps only those that are right; it tells you which were dropped and why, and you
may submit replacements once. Three to five objections, each on a different fact."""


def red_team(rv: Review, open_client) -> dict:
    """Muse Spark Open writes the pre-mortem; code keeps the objections whose cited fact is in the receipt."""
    from .redteam import get_path
    full = {rid: r["data"] for rid, r in rv.desk.receipts.items()}
    kept, dropped, rounds = [], [], []

    def submit(objections: list[dict]):
        rounds.append(len(objections))
        if len(rounds) > 2:
            return {"error": "submitted twice already: stop"}
        new = []
        for o in objections[:MAX_OBJECTIONS]:
            if len(kept) >= MAX_OBJECTIONS:
                break
            d = full.get(o.get("receipt"))
            field = str(o.get("field") or "")
            v = get_path(d, field) if d is not None else None
            seen = any(k["receipt"] == o.get("receipt") and k["field"] == field for k in kept)
            if seen and any(k["objection"] == o.get("objection") for k in kept):
                continue  # the same objection submitted again with its replacements: already kept, not dropped
            if RESTATES.search(field):
                why = "it rests on the verdict or its reasons, which only restates the decision"
            elif seen:
                why = "another objection already rests on this fact"
            elif d is None:
                why = "no such receipt"
            elif v is None:
                why = "the field is not in the receipt"
            elif not _matches(v, o.get("value")):
                why = f"the receipt holds {v!r}, not {o.get('value')!r}"
            else:
                kept.append({"id": f"O{len(kept) + 1}", **{k: o.get(k) for k in ("objection", "receipt")},
                             "field": field, "value": v})
                new.append(kept[-1]["id"])
                continue
            dropped.append({**o, "why": why})
        if len(kept) < 3 and len(rounds) == 1:
            return {"error": f"{len(kept)} objection(s) kept; submit replacements for the dropped ones (each on a "
                             "different fact from the list, against the verdict)",
                    "dropped": [{k: x.get(k) for k in ("receipt", "field", "why")} for x in dropped[-5:]]}
        return {"ok": True, "kept": len(kept), "dropped": len(dropped)}

    txt = {"type": "string"}
    item = {"type": "object", "properties": {"objection": txt, "receipt": txt, "field": txt, "value": txt},
            "required": ["objection", "receipt", "field", "value"], "additionalProperties": False}
    tool = Tool("submit", "Submit the objections.", {"type": "object", "properties": {
        "objections": {"type": "array", "items": item}}, "required": ["objections"], "additionalProperties": False},
        submit)
    compact = _compact(rv.desk)
    task = json.dumps({"proposal": rv.proposal, "appraisal": {k: rv.appraisal.get(k) for k in ("verdict", "parts")}
                       if rv.appraisal else None, "facts": facts(compact), "receipts": compact}, default=str)
    run = run_agent(open_client, MODELS["open"], RED_TEAM, task, [tool], 4, RED_TEAM_BUDGET_USD, effort="low",
                    tag="review red team")
    rv.red_team_usd += run.usd
    rv.objections = list(kept)
    rv.dropped = list(dropped)
    return {"kept": list(kept), "dropped": list(dropped), "usd": round(run.usd, 4), "stopped": run.stopped}


def tools(rv: Review, letter_client, open_client, client) -> list[Tool]:
    desk = rv.desk
    core = {t.name: t for t in orchestrator.core_tools(desk, letter_client, None, client)}
    txt, num = {"type": "string"}, {"type": "number"}
    names = site_fixes() + ["other"]

    def register_proposal(address: str, parts: list[dict], cost_usd: float, cost_covers: str, goal: str):
        if not parts or len(parts) > 4:
            return {"error": "give every part of the proposal (one to four), each as a countermeasure from the list"}
        bad = [x.get("countermeasure") for x in parts if x.get("countermeasure") not in names]
        if bad:
            return {"error": f"{bad} not in the list; choose from: {', '.join(names)}"}
        if cost_covers not in COST_COVERS:
            return {"error": f"cost_covers is one of {COST_COVERS}"}
        rv.proposal = {"address": address, "parts": [{"countermeasure": x["countermeasure"], "what": x.get("what")}
                                                     for x in parts],
                       "countermeasure": parts[0]["countermeasure"],
                       "cost_usd": float(cost_usd) if cost_usd and cost_usd > 0 else None,
                       "cost_covers": cost_covers if cost_usd and cost_usd > 0 else "not stated", "goal": goal}
        return {"receipt": desk.receipt("proposal", rv.proposal), "next": "investigate the intersection"}

    def appraise_tool():
        if rv.proposal is None:
            return {"error": "register_proposal first"}
        got = _receipt_of(desk, "choose_fixes")
        if got is None:
            return {"error": "investigate the intersection first"}
        corner = ((desk.report or {}).get("junction") or {}).get("name", "")
        if not same_corner(rv.proposal["address"], corner):
            rv.off_corner = corner
            return {"error": f"the case is about {corner}, not the proposed intersection ({rv.proposal['address']}). "
                             "A review is only of the intersection proposed: if it cannot be found, stop; never review "
                             "another corner"}
        outside = orchestrator._outside_errors(desk, [])
        if outside:  # the proposal is in a town inside the city's box: the city's record says nothing about it
            rv.outside = outside[0]
            return {"error": outside[0] + " Stop: this desk cannot review it."}
        j = (desk.report or {}).get("junction") or {}

        def fx_for_control(control):
            from . import brief
            from .countermeasures import load_cmf
            d = engineer.Desk().dossier(j["lat"], j["lon"])
            return brief.fix_options(d, load_cmf(), control=control)
        rv.appraisal = appraise_proposal(got[1], rv.proposal["parts"], rv.proposal["cost_usd"],
                                         rv.proposal["cost_covers"], fx_for_control if j.get("lat") is not None else None)
        rid = desk.receipt("appraisal", rv.appraisal)
        return {"receipt": rid, **rv.appraisal,
                "note": f"the verdict is set: {rv.appraisal['verdict_text']}. Cite {rid} for these numbers."}

    def red_team_tool():
        if rv.appraisal is None:
            return {"error": "appraise first"}
        r = red_team(rv, open_client)
        rid = desk.receipt("red_team", {"objections": r["kept"], "dropped": len(r["dropped"])})
        return {"receipt": rid, "objections": r["kept"], "dropped": len(r["dropped"]),
                "note": "answer each kept objection in the memo (answers: objection id, answer, receipt)"}

    answer = {"type": "array", "items": orchestrator._obj({"objection": txt, "answer": txt, "receipt": txt},
                                                          ["objection", "answer", "receipt"])}
    claim = {"type": "array", "items": orchestrator._obj({"text": txt, "receipt": txt}, ["text", "receipt"])}

    def gate(summary: str, verdict: str, findings: list[dict], answers: list[dict], parts: list[dict]) -> list[str]:
        errors = []
        if rv.appraisal is None:
            return ["appraise before writing the memo"]
        if rv.objections is None:
            errors.append("run red_team before writing the memo")
        if verdict != rv.appraisal["verdict"]:
            errors.append(f"the verdict is the appraisal's ({rv.appraisal['verdict']}), not {verdict!r}")
        want = sorted((x["countermeasure"], x["verdict"]) for x in rv.appraisal.get("parts") or [])
        got_parts = sorted((x.get("countermeasure"), x.get("verdict")) for x in parts)
        if want and got_parts != want:
            errors.append(f"list every part with its appraised verdict: {want}")
        places = orchestrator._places(desk)
        numbered = 0
        for k, f in enumerate(findings, 1):
            d = desk.receipts.get(f.get("receipt"))
            t = engineer.strip_places(f.get("text", ""), places)
            if not d:
                errors.append(f"finding {k} cites no receipt (got {f.get('receipt')!r})")
                continue
            if orchestrator.numbers_in(t):
                numbered += 1
            errs = orchestrator.context.FactCheck(d["data"]).text(t) if isinstance(d["data"], (dict, list)) else []
            if errs and re.search(r"\d", t):
                other = next((rid for rid, o in desk.receipts.items() if rid != f.get("receipt")
                              and isinstance(o["data"], (dict, list)) and not orchestrator.context.FactCheck(o["data"]).text(t)), None)
                if other:
                    errs = [f"these numbers are in {other} ({desk.receipts[other]['tool']}), not {f.get('receipt')}: cite {other}"]
            errors += [f"finding {k}: {e}" for e in errs + engineer.wording(t)]
        if numbered < 3:
            errors.append(f"only {numbered} findings give a number from the receipts; give at least 3")
        answered = {a.get("objection") for a in answers}
        errors += [f"objection {o['id']} ({o['objection'][:80]}) is not answered" for o in rv.objections or []
                   if o["id"] not in answered]
        for a in answers:
            if a.get("receipt") not in desk.receipts:
                errors.append(f"the answer to {a.get('objection')} cites no receipt")
            errors += [f"answer to {a.get('objection')}: {e}" for e in engineer.wording(a.get("answer", ""))]
        errors += [f"summary: {e}" for e in engineer.wording(summary)]
        if any(orchestrator.has_plate(x) for x in [summary] + [f.get("text", "") for f in findings]):
            errors.append("a licence plate is written out")
        return errors

    def check_memo(summary: str, verdict: str, findings: list[dict], answers: list[dict], parts: list[dict]):
        e = gate(summary, verdict, findings, answers, parts)
        return {"would_publish": not e, "problems": e[:15]}

    def finish(summary: str, verdict: str, findings: list[dict], answers: list[dict], parts: list[dict]):
        e = gate(summary, verdict, findings, answers, parts)
        if e:
            return {"error": "refused by the memo gate", "errors": e[:12]}
        rv.final = {"summary": summary, "verdict": verdict, "findings": findings, "answers": answers, "parts": parts}
        return {"ok": True}

    part_verdict = {"type": "array", "items": orchestrator._obj(
        {"countermeasure": {"type": "string", "enum": names}, "verdict": {"type": "string", "enum": list(VERDICTS)}},
        ["countermeasure", "verdict"])}
    memo = orchestrator._obj({"summary": txt, "verdict": {"type": "string", "enum": list(VERDICTS)},
                              "parts": part_verdict, "findings": claim, "answers": answer},
                             ["summary", "verdict", "parts", "findings", "answers"])
    return [
        Tool("register_proposal", "Register the proposal: the intersection; every part as a countermeasure from the "
             "list (with what it is); the cost in dollars (0 if not stated) and what it pays for; the goal.",
             orchestrator._obj({"address": txt, "parts": {"type": "array", "items": orchestrator._obj(
                 {"countermeasure": {"type": "string", "enum": names}, "what": txt}, ["countermeasure", "what"])},
                                "cost_usd": num, "cost_covers": {"type": "string", "enum": list(COST_COVERS)},
                                "goal": txt}, ["address", "parts", "cost_usd", "cost_covers", "goal"]),
             register_proposal),
        core["investigate"],
        Tool("appraise", "Code tests the registered proposal against the corner's evidence and sets the verdict.",
             orchestrator._obj({}, []), appraise_tool),
        core["program_record"],
        Tool("red_team", "An independent model writes the pre-mortem; code keeps only objections whose facts check out.",
             orchestrator._obj({}, []), red_team_tool),
        Tool("check_memo", "Dry-run the memo gate; fix what it names, then finish.", memo, check_memo),
        Tool("finish", "Publish the decision memo.", memo, finish),
    ]


def task_for(text: str, city_name: str) -> str:
    return (f"Review this proposed street-safety project in {city_name} before the agency commits to it: "
            f"\"{text.strip()}\".")


def review(text: str, city: str, client=None, letter_client=None, open_client=None, budget_usd: float = 0.50,
           max_turns: int = 20, out_dir: Path | None = None) -> dict:
    """Review one proposal and save the memo. The clients default to Muse Spark (Meta API) and Muse Spark Open."""
    from . import check
    t0 = time.time()
    if not text or not text.strip() or len(text) > MAX_INPUT:
        return {"status": "error", "reason": f"give the proposal in at most {MAX_INPUT} characters"}
    c, why = check.supported(city)
    if c is None:
        return {"status": "unsupported_city", "reason": why, "city": city, "input": text}
    if client is None:
        from .meta_client import MetaClient
        client = MetaClient(SETTINGS)
    if open_client is None:
        from .openclient import OpenWeightsClient
        open_client = OpenWeightsClient()
    rv = Review(c["id"])
    rv.desk.task = text  # the proposal as written: a town it names is checked against the city's limits
    run = run_agent(client, orchestrator.MODEL, INSTRUCTIONS, task_for(text, c["name"]),
                    tools(rv, letter_client, open_client, client), max_turns, budget_usd, effort="low",
                    tag=f"review {text[:40]}", escalate_after=3,
                    required=("register_proposal", "investigate", "appraise", "red_team"), governor=True)
    rep = rv.desk.report or {}
    out = {"status": "published" if rv.final else "abstained",
           "reason": None if rv.final else (rv.outside if rv.outside else
                                             f"the proposed intersection could not be found; the agent reached "
                                             f"{rv.off_corner}, which is not it" if rv.off_corner
                                             else _last_refusal(run) or f"not published ({run.stopped})"),
           "city": c["id"], "city_name": c["name"], "input": orchestrator.redact(text),
           "proposal": rv.proposal, "corner": (rep.get("junction") or {}).get("name"),
           "verdict": (rv.appraisal or {}).get("verdict"), "verdict_text": (rv.appraisal or {}).get("verdict_text"),
           "appraisal": rv.appraisal, "objections": rv.objections,
           "objections_dropped": [{k: x.get(k) for k in ("objection", "receipt", "field", "why")} for x in rv.dropped],
           "memo": rv.final, "letter": orchestrator.redact(((rep.get("findings") or {}).get("draft_request") or {})
                                                            .get("letter") or "") or None,
           "receipts": {k: {"tool": v["tool"]} for k, v in rv.desk.receipts.items()},
           "cost_usd": {"meta": round(run.usd, 4), "open_weights_red_team": round(rv.red_team_usd, 4)},
           "turns": run.turns, "seconds": round(time.time() - t0, 1), "asof": config_asof().isoformat(),
           "trace": [{"turn": s.turn, "tool": s.tool,
                      "error": (s.result or {}).get("error") if isinstance(s.result, dict) else None,
                      "errors": (s.result or {}).get("errors") if isinstance(s.result, dict) else None}
                     for s in run.steps]}
    save(out, out_dir, {rid: {"tool": r["tool"], "data": r["data"]} for rid, r in rv.desk.receipts.items()})
    return out


def save(out: dict, out_dir: Path | None = None, receipts: dict | None = None) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", (out.get("corner") or out.get("input") or "").lower()).strip("_")[:40] or "review"
    d = out_dir or SETTINGS.runs_dir / "reviews" / f"{stamp}_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(portable(json.dumps(out, indent=1, default=str)))
    (d / "memo.md").write_text(memo_md(out))
    if receipts:  # the data behind every receipt id the memo cites, so a number can be checked without a rerun
        (d / "receipts.json").write_text(orchestrator.redact(portable(json.dumps(receipts, indent=1, default=str))))
    out["saved"] = portable(str(d))
    return d


def memo_md(r: dict) -> str:
    """The decision memo as a readable page."""
    p = r.get("proposal") or {}
    a = r.get("appraisal") or {}
    L = [f"# Before you commit: {p.get('countermeasure') or 'proposal'} at {r.get('corner') or p.get('address') or '?'}",
         "", f"**Verdict (set by code):** {r.get('verdict_text') or r.get('status')}", ""]
    if r.get("reason"):
        L += [f"**Not published:** {r['reason']}", ""]
    L += [f"- **Proposal:** {r.get('input')}", f"- **Cost stated:** {('$' + format(p['cost_usd'], ',.0f')) if p.get('cost_usd') else 'not stated'}",
          f"- **Records as of:** {r.get('asof')}",
          f"- **Cost of this review:** ${(r.get('cost_usd') or {}).get('meta')} Meta API + "
          f"${(r.get('cost_usd') or {}).get('open_weights_red_team')} Muse Spark Open, {r.get('seconds')} s", ""]
    if len(a.get("parts") or []) > 1:
        L += ["## Each part", "", "| Part | Verdict |", "|---|---|"] + [
            f"| {x['countermeasure'] if x['countermeasure'] != 'other' else x.get('what')} | {x['verdict_text']} |"
            for x in a["parts"]] + [""]
    if a.get("reasons"):
        L += ["## Why", ""] + [f"- {x}" for x in a["reasons"]] + [""]
    m = r.get("memo") or {}
    if m:
        L += [m.get("summary", ""), "", "## Findings", ""] + [f"- {f.get('text')} [{f.get('receipt')}]"
                                                              for f in m.get("findings") or []] + [""]
    if r.get("objections"):
        ans = {x.get("objection"): x for x in m.get("answers") or []}
        L += ["## Pre-mortem (red team, facts checked by code)", ""]
        for o in r["objections"]:
            L.append(f"- **{o['id']}** {o['objection']} [{o['receipt']}: {o['field']} = {o['value']}]")
            if o["id"] in ans:
                L.append(f"  - *Answer:* {ans[o['id']].get('answer')} [{ans[o['id']].get('receipt')}]")
        L.append("")
    if r.get("objections_dropped"):
        L += [f"*{len(r['objections_dropped'])} more objection(s) were dropped by code: "
              + "; ".join(sorted({x.get('why', '') for x in r['objections_dropped']}))[:400] + ".*", ""]
    if r.get("letter"):
        L += ["## Draft work order (review it; nothing is sent)", "", r["letter"], ""]
    return "\n".join(L)


def registered_inputs(spec: dict) -> list[dict]:
    """The proposals a registered run reviews: the test set's rows in the spec's split."""
    rows = json.loads(EXAMPLES.read_text())["proposals"]
    return [r for r in rows if r["split"] == spec["split"]]


def run_registered(spec_id: str, client, letter_client, open_client) -> dict:
    """A registered review run (validation/experiments/T26*.json), resumed from its saved results."""
    import os
    from .evaluate import RESULTS_DIR
    from .cache import ReplayMiss
    from .cost import BudgetExceeded
    sp = json.loads((Path(__file__).resolve().parent.parent / "validation" / "experiments" / f"{spec_id}.json").read_text())
    os.environ["NML_ASOF"] = sp["asof"]
    path = RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"
    done = {r["id"]: r for r in (json.loads(path.read_text()).get("cases", []) if path.exists() else [])}
    out = []
    for inp in registered_inputs(sp):
        if inp["id"] in done:
            out.append(done[inp["id"]])
            continue
        try:
            r = review(inp["proposal"], inp["city"], client, letter_client, open_client, budget_usd=sp["budget_usd"])
        except (ReplayMiss, BudgetExceeded):
            raise
        except Exception as e:  # a live failure is a result, and the run goes on
            r = {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300]}
        r = {"id": inp["id"], "city_id": inp["city"], "source": inp["source"], **r}
        out.append(r)
        print(inp["id"], r.get("status"), r.get("verdict"), r.get("cost_usd"), r.get("seconds"), flush=True)
        path.write_text(orchestrator.redact(portable(json.dumps({"id": spec_id, "cases": out}, indent=1, default=str))))
    return {"id": spec_id, "cases": out}


def run_summary(res: dict, spec: dict) -> dict:
    """The registered rule, measured."""
    cases, rule = res["cases"], spec["rule"]
    pub = [c for c in cases if c.get("status") == "published"]
    usd = [float((c.get("cost_usd") or {}).get("meta") or 0) + float((c.get("cost_usd") or {}).get("open_weights_red_team") or 0)
           for c in cases]
    kept = sum(len(c.get("objections") or []) for c in pub)
    on_corner = [c for c in pub if same_corner((c.get("proposal") or {}).get("address") or c.get("input", ""),
                                               c.get("corner") or "")]
    out = {"inputs": len(cases), "published": len(pub), "on_proposed_corner": len(on_corner),
           "verdicts": {v: sum(c.get("verdict") == v for c in pub) for v in VERDICTS},
           "verdict_is_codes": all((c.get("memo") or {}).get("verdict") == c.get("verdict") for c in pub),
           "red_team_ran": sum(c.get("objections") is not None for c in pub), "objections_kept": kept,
           "memos_with_3_objections": sum(len(c.get("objections") or []) >= 3 for c in pub),
           "objections_on_the_verdict": sum(bool(RESTATES.search(str(o.get("field") or ""))) for c in pub
                                            for o in c.get("objections") or []),
           "mean_usd": round(sum(usd) / len(usd), 4) if usd else None, "total_usd": round(sum(usd), 4),
           "mean_seconds": round(sum(float(c.get("seconds") or 0) for c in cases) / len(cases), 1) if cases else None}
    met = {"published": len(pub) >= rule["min_published"],
           **({"on_proposed_corner": len(on_corner) == len(pub)} if rule.get("every_memo_on_proposed_corner") else {}),
           "verdict_is_codes": out["verdict_is_codes"],
           "red_team_on_every_memo": out["red_team_ran"] == len(pub),
           **({"objections": out["memos_with_3_objections"] >= rule["min_memos_with_3_objections"]
               and out["objections_on_the_verdict"] == 0} if "min_memos_with_3_objections" in rule else {}),
           "cost": out["mean_usd"] is not None and out["mean_usd"] <= rule["max_mean_usd"]}
    out["met"], out["rule_met"] = met, all(met.values())
    return out
