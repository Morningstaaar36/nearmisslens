"""Runs of the desk and of the governed agent, from their registered specs (validation/experiments/T2*.json), so
every reported result can be rerun from the repo; with --replay the cached answers give the same results.

A spec fixes everything a run depends on: the cases, the budget and turn limit per case, whether the model-read
claim check is on, and the date of the inbox snapshot its 311 cases come from. A run resumes from the cases already
in its results file; a replay that is missing an answer stops the run instead of being recorded as a failed case."""
from __future__ import annotations

import json

from . import engineer, inbox, orchestrator
from .cache import ReplayMiss
from .config import ROOT, SETTINGS, portable
from .cost import BudgetExceeded
from .evaluate import RESULTS_DIR


def spec(spec_id: str) -> dict:
    return json.loads((ROOT / "validation" / "experiments" / f"{spec_id}.json").read_text())


def results_path(spec_id: str):
    return RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"


def inbox_tasks(city: str, date: str | None) -> list[dict]:
    """The city's triaged inbox on the spec's date (one report per distinct address, most crash-exposed first)."""
    replay = SETTINGS.replay
    SETTINGS.replay = True  # the inbox is read from its saved snapshot, never fetched again for a registered run
    try:
        tri = inbox.triage(city, inbox.fetch(inbox.adapter(city), date=date))
    finally:
        SETTINGS.replay = replay
    distinct = []
    for r in tri:
        if r["address"] not in [x["address"] for x in distinct]:
            distinct.append(r)
    return distinct


def run_desk(spec_id: str, client, letter_client, fresh: bool = False) -> dict:
    sp = spec(spec_id)
    limits = {"budget_usd": sp.get("budget_usd", 0.50), "max_turns": sp.get("max_turns", 22)}
    check_client = client if sp.get("model_check") else None
    path = results_path(spec_id)
    done = [] if fresh or not path.exists() else json.loads(path.read_text()).get("cases", [])
    inboxes, out, pages = {}, [], {}
    for k, case in enumerate(sp["cases"]):
        task = case.get("task")
        if task is None:  # an inbox case: the report at that rank in the city's triaged inbox
            city = case["city"]
            if city not in inboxes:
                inboxes[city] = inbox_tasks(city, sp.get("inbox_date"))
            r = inboxes[city][case["inbox_rank"]]
            task = inbox.task(r, city, with_record=bool(sp.get("inbox_record_source")))
            if sp.get("inbox_record_source"):
                url, text = inbox.record(r, city)
                pages[k] = {url: text}
        if k < len(done) and done[k].get("task") in (task, orchestrator.redact(task)):
            out.append(done[k])  # resumed: this case already ran under this spec
            continue
        try:
            r = orchestrator.run_case(task, case["city"], client, letter_client=letter_client,
                                      model_check_client=check_client, pages=pages.get(k), **limits)
        except (ReplayMiss, BudgetExceeded):
            raise  # a replay without the saved answer, or the total budget spent: stop, never record as a result
        except Exception as e:  # a live failure of one case is a result (reported), and the run goes on
            r = {"task": task, "city": case["city"], "finished": False, "stopped": f"error: {type(e).__name__}: {e}"[:300]}
        r["kind"] = case["kind"]
        out.append(r)
        print(case["kind"], case["city"], "finished", r.get("finished"), r.get("stopped"), "usd", r.get("usd"), flush=True)
        path.write_text(orchestrator.redact(portable(json.dumps(  # no licence plate is kept, even from an input
            {"id": spec_id, **limits, "model_check": bool(check_client), "cases": out}, indent=1, default=str))))
    return {"id": spec_id, "cases": out}


def run_governed(client, spec_id: str = "T22") -> list[dict]:
    """T22: the same top corners as the first agent run, with the loop governor (cities and counts from the spec)."""
    sp = spec(spec_id)
    reps = []
    for c in sp["cities"]:
        reps += engineer.agent_cases(c["city"], client, top=c["top"],
                                     out_dir=SETTINGS.runs_dir / "engineer" / sp["out_name"] / c["city"], governor=True)
    return reps
