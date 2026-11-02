"""Runs of the desk and of the governed agent, from their registered specs (validation/experiments/T21*.json), so
every reported result can be rerun from the repo; with --replay the cached answers give the same results."""
from __future__ import annotations

import json

from . import engineer, inbox, orchestrator
from .config import ROOT, SETTINGS, portable
from .evaluate import RESULTS_DIR


def run_desk(spec_id: str, client, letter_client) -> dict:
    spec = json.loads((ROOT / "validation" / "experiments" / f"{spec_id}.json").read_text())
    inboxes = {}
    out = []
    for case in spec["cases"]:
        task = case.get("task")
        if task is None:  # an inbox case: the report at that rank in the city's triaged inbox (distinct addresses)
            city = case["city"]
            if city not in inboxes:
                replay, SETTINGS.replay = SETTINGS.replay, True
                tri = inbox.triage(city, inbox.fetch(inbox.adapter(city)))
                SETTINGS.replay = replay
                distinct = []
                for r in tri:
                    if r["address"] not in [x["address"] for x in distinct]:
                        distinct.append(r)
                inboxes[city] = distinct
            task = inbox.task(inboxes[city][case["inbox_rank"]], city)
        try:
            r = orchestrator.run_case(task, case["city"], client, letter_client=letter_client)
        except Exception as e:
            r = {"task": task, "city": case["city"], "finished": False, "stopped": f"error: {type(e).__name__}: {e}"[:300]}
        r["kind"] = case["kind"]
        out.append(r)
        print(case["kind"], case["city"], "finished", r.get("finished"), r.get("stopped"), "usd", r.get("usd"), flush=True)
        (RESULTS_DIR / "bench" / f"experiment_{spec_id}.json").write_text(
            portable(json.dumps({"id": spec_id, "cases": out}, indent=1, default=str)))
    return {"id": spec_id, "cases": out}


def run_governed(client, out_name: str = "agent_v2") -> list[dict]:
    """T22: the same top corners as the first agent run, with the loop governor."""
    reps = []
    for city, top in (("nyc", 20), ("seattle", 5), ("dc", 5), ("sf", 5)):
        reps += engineer.agent_cases(city, client, top=top, out_dir=SETTINGS.runs_dir / "engineer" / out_name / city,
                                     governor=True)
    return reps
