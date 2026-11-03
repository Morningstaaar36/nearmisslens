"""NML-Bench T24: what the desk's tools and gates add. Muse Spark alone, with Meta's web_search and nothing else, gets
the same real inputs as a registered desk run and writes its findings and sources; nothing refuses anything. Code then
scores what it wrote: are its quotes on the page they cite, and are the numbers it states about the corner the
record's numbers (the same receipts the desk's investigate built for that corner, rebuilt from the cache)?"""
from __future__ import annotations

import json
import time

from . import orchestrator
from .agent import Tool, run_agent
from .config import MODELS, SETTINGS, portable
from .evaluate import RESULTS_DIR

MODEL = MODELS["orchestrator"]
INSTRUCTIONS = (
    "You work for a city's street-safety team. Given a real-world input (a news story, a statement or a resident's "
    "report), use web_search to find the facts and the intersection's crash history, and check what was claimed. "
    "Finish with: a short summary for the safety team; findings, each a plain sentence (the injury crashes at the "
    "intersection and what they have in common, the city's verdict on any program credited, the fix the evidence "
    "supports, who owns the road, and the verdict on each claim you checked); and sources, each with its URL and an "
    "exact quote from that page.")


def run_case(task: str, client, budget_usd: float = 0.30, max_turns: int = 8) -> dict:
    out = {}
    txt = {"type": "string"}
    obj = orchestrator._obj

    def finish(summary: str, findings: list[str], sources: list[dict]):
        out.update(summary=summary, findings=findings, sources=sources)
        return {"ok": True}
    tools = [Tool("finish", "Publish the summary, findings and sources.",
                  obj({"summary": txt, "findings": {"type": "array", "items": txt},
                       "sources": {"type": "array", "items": obj({"url": txt, "quote": txt}, ["url", "quote"])}},
                      ["summary", "findings", "sources"]), finish)]
    t0 = time.time()
    run = run_agent(client, MODEL, INSTRUCTIONS, task, tools, max_turns, budget_usd, effort="low",
                    tag=f"alone {task[:40]}", server_tools=[{"type": "web_search"}], include=("web_search_call.results",))
    return {"task": task, "finished": bool(out), "final": out or None, "stopped": run.stopped, "turns": run.turns,
            "usd": round(run.usd, 4), "seconds": round(time.time() - t0, 1)}


def score(case: dict, desk_case: dict) -> dict:
    """Quotes: verified / absent / unreadable on their page. Findings with numbers, by the desk's own claim check
    against the record the desk case built (rebuilt from the cache, in the window that run read): consistent when a
    number in it was tested and matched against any of the corner's receipts, differing when the crash record has
    another value for what it names, else not checkable."""
    f = case.get("final") or {}
    quotes = [orchestrator.quote_check(s.get("quote", ""), s.get("url", "")) for s in f.get("sources") or []]
    try:
        rec = orchestrator.replay_record(desk_case) if desk_case.get("corner") else {}
    except Exception:
        rec = {}
    places = orchestrator._places(orchestrator.Desk(desk_case.get("city")))
    if desk_case.get("corner"):
        places.places.add(desk_case["corner"].split(",")[0])
    verdicts = []
    for text in f.get("findings") or []:
        if not orchestrator.numbers_in(text) or not rec:
            continue
        got = {t: orchestrator.claim_verdict(text, rec[t], places)[:2] for t in RECEIPTS if t in rec}
        if any(v == "consistent with the record" for v, _ in got.values()):
            kind, why = "consistent", []
        elif got.get("choose_fixes", ("",))[0] == "differs from the record":
            kind, why = "differs", got["choose_fixes"][1]
        else:
            kind, why = "not checkable", next(iter(got.values()), ("", []))[1]
        verdicts.append({"text": text, "verdict": kind, "reasons": why[:3]})
    return {"quotes": quotes, "findings": verdicts, "record": bool(rec)}


RECEIPTS = ("choose_fixes", "test_programs", "root_cause")  # the corner's crash record, program record, patterns


def rescore(spec_id: str, desk_run: str) -> dict:
    """Score a finished baseline run again with the current scoring code (the models' answers are not rerun)."""
    desk = json.loads((RESULTS_DIR / "bench" / f"experiment_{desk_run}.json").read_text())
    path = RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"
    res = json.loads(path.read_text())
    for c, dcase in zip(res["cases"], desk["cases"]):
        c["score"] = score(c, dcase)
    path.write_text(orchestrator.redact(portable(json.dumps(res, indent=1, default=str))))
    return res


def run(spec_id: str, client, desk_run: str) -> dict:
    """The baseline on a registered desk run's inputs; each case scored against the corner that desk case investigated."""
    desk = json.loads((RESULTS_DIR / "bench" / f"experiment_{desk_run}.json").read_text())
    path = RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"
    done = json.loads(path.read_text())["cases"] if path.exists() else []
    out = []
    for k, dcase in enumerate(desk["cases"]):
        if k < len(done) and done[k].get("task") == dcase["task"]:
            out.append(done[k])
            continue
        r = run_case(dcase["task"], client)
        r.update(kind=dcase.get("kind"), city=dcase.get("city"), desk_corner=dcase.get("corner"), score=score(r, dcase))
        out.append(r)
        print(dcase.get("kind"), dcase.get("city"), "finished", r["finished"], "usd", r["usd"], flush=True)
        path.write_text(orchestrator.redact(portable(json.dumps({"id": spec_id, "desk_run": desk_run, "cases": out},
                                                                indent=1, default=str))))
    return {"id": spec_id, "cases": out}


def summary(res: dict) -> dict:
    q = [x for c in res["cases"] for x in (c.get("score") or {}).get("quotes", [])]
    f = [x["verdict"] for c in res["cases"] for x in (c.get("score") or {}).get("findings", [])]
    return {"cases": len(res["cases"]), "finished": sum(bool(c.get("finished")) for c in res["cases"]),
            "quotes": len(q), "quotes_verified": q.count("verified"), "quotes_absent": q.count("absent"),
            "quotes_unreadable": q.count("unreadable"), "number_findings": len(f),
            "consistent": f.count("consistent"), "differs": f.count("differs"), "not_checkable": f.count("not checkable"),
            "usd_per_case": round(sum(c.get("usd") or 0 for c in res["cases"]) / max(len(res["cases"]), 1), 4)}
