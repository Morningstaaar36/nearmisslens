"""Registered runs of `nml check` (validation/experiments/T25*.json): the path reviewers use, on inputs fixed before
any run, scored by the spec's rule. A run resumes from the inputs already in its results file; a replay missing an
answer, or the total budget spent, stops the run instead of being recorded as a result."""
from __future__ import annotations

import json
import os
from statistics import mean

from . import check, orchestrator
from .cache import ReplayMiss
from .config import ROOT, portable
from .cost import BudgetExceeded
from .evaluate import RESULTS_DIR


def spec(spec_id: str) -> dict:
    return json.loads((ROOT / "validation" / "experiments" / f"{spec_id}.json").read_text())


def results_path(spec_id: str):
    return RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"


def run(spec_id: str, client, letter_client) -> dict:
    sp = spec(spec_id)
    os.environ["NML_ASOF"] = sp["asof"]  # the records' date is part of the spec (the deployed app reads the same)
    path = results_path(spec_id)
    done = {r["id"]: r for r in (json.loads(path.read_text()).get("cases", []) if path.exists() else [])}
    out = []
    for inp in sp["inputs"]:
        if inp["id"] in done:
            out.append(done[inp["id"]])  # resumed
            continue
        try:
            r = check.check(inp["input"], inp["city"], kind=inp["kind"], budget_usd=sp["budget_usd"], client=client,
                            letter_client=letter_client, model_check_client=client)
        except (ReplayMiss, BudgetExceeded):
            raise
        r = {"id": inp["id"], "control": inp.get("control"), **r}
        out.append(r)
        print(inp["id"], r["status"], "usd", (r.get("cost_usd") or {}).get("meta"), r.get("seconds"), "s", flush=True)
        path.write_text(orchestrator.redact(portable(json.dumps({"id": spec_id, "cases": out}, indent=1, default=str))))
    return {"id": spec_id, "cases": out}


def _verdicts(r: dict) -> list[str]:
    return [str(c.get("verdict") or "") for c in r.get("claims") or []]


def summary(res: dict, spec_id: str | None = None) -> dict:
    """The spec's rule, measured. Each control is scored by what it was put in to catch."""
    sp = spec(spec_id or res["id"])
    rule, cases = sp["rule"], res["cases"]
    real = [c for c in cases if not c.get("control")]
    pub = [c for c in real if c["status"] == "published"]
    quotes = [s for c in cases if c["status"] == "published" for s in c.get("sources") or []]
    verified = sum(s.get("quote_check") == "verified" for s in quotes)
    plates = sum(orchestrator.has_plate(json.dumps({k: c.get(k) for k in ("summary", "findings", "sources", "letter")}))
                 for c in cases if c["status"] == "published")
    usd = [float((c.get("cost_usd") or {}).get("meta") or 0) for c in cases]
    ctl = {c["control"]: c for c in cases if c.get("control")}
    off = ctl.get("offtopic")
    false = ctl.get("false_claim")
    out = {
        "inputs": len(cases), "real": len(real), "published_real": len(pub),
        "by_input": {c["id"]: c["status"] for c in cases},
        "quotes_published": len(quotes), "quotes_verified": verified,
        "verified_share": round(verified / len(quotes), 3) if quotes else None,
        "plates_published": plates,
        "mean_usd": round(mean(usd), 4) if usd else None, "total_usd": round(sum(usd), 4),
        "mean_seconds": round(mean(float(c.get("seconds") or 0) for c in cases), 1) if cases else None,
        "offtopic_published": None if off is None else off["status"] == "published",
        "false_claim_status": None if false is None else false["status"],
        "false_claim_verdicts": None if false is None else _verdicts(false),
    }
    out["false_claim_consistent"] = None if false is None else any(
        v.startswith("consistent") for v in out["false_claim_verdicts"])
    met = {
        "published": len(pub) >= rule["min_published_real"],
        "cost": out["mean_usd"] is not None and out["mean_usd"] <= rule["max_mean_usd"],
        "quotes": out["verified_share"] is None or out["verified_share"] >= rule["min_verified_quote_share"],
        "plates": plates == 0,
        "control_offtopic": out["offtopic_published"] is False,
        "control_false_claim": out["false_claim_consistent"] is False,
    }
    out["met"] = met
    out["rule_met"] = len(cases) == len(sp["inputs"]) and all(met.values())
    return out
