"""Manager agent: Muse Wonder runs a junction's safety review end to end. It reads the audit, has Muse Spark's video
reviews and the Proposer/Skeptic/Judge panel weigh in, checks residents' complaints with the intake agent, looks up the
fix test and hotspot persistence, asks a person to sign off, and writes a work order. Every claim passes the audit's
grounding checker before the work order is accepted; three refusals stop the run for a person (Meta's verifiable-agent
pattern). The run's reasoning summaries and tool calls form the mission-control timeline shown in the viewer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

from . import ask, panel
from .agent import Tool, run_agent
from .config import SETTINGS
from .evaluate import RESULTS_DIR
from .meta_client import MetaClient

MODEL = "muse-wonder-1.0"
MAX_TURNS = 16
BUDGET_USD = 0.6
INSTRUCTIONS = (
    "You manage a road-safety review of one signalised junction for the city. Your team: the audit (measured "
    "near-misses and hotspots from drone video), Muse Spark's video reviews of the worst conflicts, a review panel that "
    "argues countermeasures, an intake officer who checks residents' complaints against the evidence, a fix test on the "
    "measured traffic, and a persistence check across recording days. Work efficiently: start with site_summary, use "
    "the cheapest tool that answers each question, check every complaint you are given, and convene the panel once. "
    "Before writing the work order, call request_signoff with a short summary of what you will recommend. Then call "
    "finish with the work order: for each hotspot you act on, the countermeasure CMF ids (only ones the audit kept), "
    "the evidence (numbers from the tools only) and what remains uncertain. If finish is rejected, fix the errors.")


def _bench(name: str) -> dict | None:
    p = RESULTS_DIR / "bench" / name
    return json.loads(p.read_text()) if p.exists() else None


def run(client: MetaClient, audit_name: str, complaints: list[str], cmf: pd.DataFrame,
        signoff: Callable[[str], dict] | None = None, tag: str = "office") -> dict:
    facts, memo_md = ask.load(audit_name, SETTINGS.runs_dir)
    site = facts.get("site") or audit_name
    g = panel.Grounding(facts, memo_md)
    reads = panel.read_tools(facts, cmf, g)
    by_rank = {f["rank"]: f for f in facts["findings"]}
    frames = Path(SETTINGS.data_dir) / "work" / "ask_frames"
    signoffs: list[dict] = []
    attempts: list[dict] = []
    stored_panel = SETTINGS.runs_dir / "audit" / audit_name / "panel.json"

    def shown(x):
        g.add(x)
        return x

    def video_reviews(rank: int) -> dict:
        f = by_rank.get(rank)
        if f is None:
            return {"error": f"hotspot {rank} does not exist"}
        v = f.get("verification") or {}
        return shown({"rank": rank, "reviewed": v.get("reviewed", 0), "judged_real": v.get("real", 0),
                      "evasive_action": v.get("evasive", 0),
                      "verdicts": [{k: d.get(k) for k in ("measure", "value", "real_conflict", "evasive_action", "reason")}
                                   for d in v.get("verdicts", [])]})

    def convene_panel() -> dict:
        p = json.loads(stored_panel.read_text()) if stored_panel.exists() else panel.run_panel(
            client, facts, memo_md, cmf, f"{tag} panel")
        return shown({"status": p.get("status"), "decisions": p.get("decisions"), "objections": p.get("objections"),
                      "claims_caught_by_checker": p.get("caught", 0)})

    def check_complaint(text: str) -> dict:
        out = ask.answer(client, text, facts, memo_md, cmf, frames, f"{tag} complaint", model="muse-spark-1.3-contributor",
                         budget_usd=0.02)
        r = out["result"] or {}
        return shown({"verdict": r.get("verdict"), "rank": r.get("rank"), "answer": r.get("answer"),
                      "cmf_ids": r.get("cmf_ids"), "cost_usd": out["usd"]})

    def fix_test() -> dict:
        b = _bench("fix_test.json")
        if not b:
            return {"error": "fix test not run"}
        site_rows = [r for r in b["per_flight"] if audit_name.startswith(("test", "dev")) and r["site"] == "FIDRT"
                     or audit_name.startswith("heldout") and r["site"] == "FI"]
        return shown({"intervention": "remove every road user that entered on red, re-run the conflict engine",
                      "note": "upper bound on conflicts in edited trajectories, not crashes avoided",
                      "flights": site_rows, "all_sites": b["summary"]})

    def persistence() -> dict:
        b = _bench("persistence.json")
        if not b:
            return {"error": "persistence not run"}
        return shown({"summary": b["summary"], "note": "Kendall tau of cell conflict rates between recordings of the "
                                                       "same junction on different days"})

    def request_signoff(summary: str) -> dict:
        decision = signoff(summary) if signoff else {"approved": True, "by": "auto (benchmark run)", "note": ""}
        signoffs.append({"summary": summary, **decision})
        return decision

    def finish(work_order: str, cmf_ids: list[str], ranks: list[int]) -> dict:
        errors = g.text(work_order)
        for r in ranks:
            if r not in by_rank:
                errors.append(f"hotspot {r} does not exist")
        for c in cmf_ids:
            if not any(c in g.kept.get(r, {}) for r in ranks):
                errors.append(f"CMF {c} is not kept by the audit for hotspots {ranks}")
        if not signoffs:
            errors.append("call request_signoff before the work order")
        elif not signoffs[-1].get("approved"):
            errors.append("the person did not approve; revise the plan and ask again")
        attempts.append({"work_order": work_order, "cmf_ids": cmf_ids, "ranks": ranks, "errors": errors})
        return {"error": "rejected by the grounding checker", "errors": errors} if errors else {"ok": True}

    obj = panel._obj
    tools = reads + [
        Tool("video_reviews", "Muse Spark's verdicts on the worst conflicts of a hotspot, from event-centred video.",
             obj({"rank": {"type": "integer"}}, ["rank"]), video_reviews),
        Tool("convene_panel", "The Proposer, Skeptic and Judge argue the audit's countermeasures (once).", obj({}, []),
             convene_panel),
        Tool("check_complaint", "The intake officer checks one resident complaint against the evidence.",
             obj({"text": {"type": "string"}}, ["text"]), check_complaint),
        Tool("fix_test", "Conflicts removed when red-light entrants are removed, against random removal.", obj({}, []),
             fix_test),
        Tool("persistence", "Whether hotspot rankings persist across recording days.", obj({}, []), persistence),
        Tool("request_signoff", "Ask the city engineer to approve the plan before the work order.",
             obj({"summary": {"type": "string"}}, ["summary"]), request_signoff),
        Tool("finish", "Submit the work order.", obj({"work_order": {"type": "string"},
                                                      "cmf_ids": {"type": "array", "items": {"type": "string"}},
                                                      "ranks": {"type": "array", "items": {"type": "integer"}}},
                                                     ["work_order", "cmf_ids", "ranks"]), finish),
    ]
    task = f"Junction audit: {site}.\nResident complaints to check:\n" + "\n".join(f"- {c}" for c in complaints)
    r = run_agent(client, MODEL, INSTRUCTIONS, task, tools, MAX_TURNS, BUDGET_USD, effort="low", tag=tag,
                  summaries=True, escalate_after=3)
    accepted = next((a for a in attempts if not a["errors"]), None)
    return {"audit": audit_name, "complaints": complaints, "stopped": r.stopped, "turns": r.turns,
            "usd": round(r.usd, 4), "refusals": r.refusals, "signoffs": signoffs, "work_order": accepted,
            "rejected_attempts": [a for a in attempts if a["errors"]], "timeline": r.timeline()}


def write(result: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / "office.json"
    p.write_text(json.dumps(result, indent=1, default=str))
    return p
