"""Ask the engineer: a free question about a corner, answered by Muse Spark Open from that corner's saved receipts.

The agent reads the receipts of the corner's case (what the crashes have in common, the city's programs, the fixes, who
must act, the request), the mechanisms the miner confirmed on sealed years, and the site check. It can also look across
the city's corners. Its answer goes through the same finish gate as the engineer: every sentence cites a receipt, its
numbers must be that receipt's values for their labels, and "caused", "failed" and "proves" are refused. Refused
sentences are returned with the reason, so the page can show them struck through. No new data is fetched."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import engineer
from .config import SETTINGS
from .evaluate import RESULTS_DIR
from .config import MODELS

INSTRUCTIONS = (
    "You answer a city traffic engineer's or a resident's question about one street corner, using only the receipts "
    "your tools return. Read what you need (read_receipt for the corner's case; mechanisms for crash patterns confirmed "
    "on later years; site_check for what the aerial photo shows; find_corners to compare with other corners). Then call "
    "finish with a short answer (at most 5 claims), each claim citing the receipt id it rests on and using only that "
    "receipt's numbers next to the right words. Say 'have in common', never 'caused'; 'not shown', never 'failed'. If the "
    "receipts cannot answer, say so in one claim citing the closest receipt. If finish is refused, fix the claims it names.")


def _report(city: str, slug: str) -> dict:
    p = SETTINGS.runs_dir / "engineer" / city / f"{slug}.json"
    if not p.exists():
        raise ValueError(f"no saved case for {slug!r} in {city}; run nml pages")
    return {**json.loads(p.read_text()), "source": "saved"}  # built earlier, as of its asof date; not a live run


def _extra(name: str, key: str, slug: str) -> dict | None:
    """A corner's row from an experiment's results (the miner's agent findings, the site check)."""
    p = RESULTS_DIR / "bench" / name
    if not p.exists():
        return None
    res = json.loads(p.read_text())
    rows = [r for r in res.get(key, []) if r.get("corner", r.get("slug")) == slug and not r.get("null")
            and r.get("arm", "agent") == "agent"]
    return rows[0] if rows else None


def desk_for(report: dict) -> engineer.Desk:
    """A desk holding the corner's saved receipts and their data, so new claims can cite them."""
    desk = engineer.Desk(receipts=list(report["receipts"]),
                         data={r["id"]: report["findings"][r["tool"]] for r in report["receipts"]
                               if r["tool"] in report["findings"]})
    desk.places.add(report["junction"]["name"].split(",")[0])
    return desk


def ask(city: str, slug: str, question: str, client, budget_usd: float = 0.05, gated: bool = True) -> dict:
    """gated=False is NML-Bench T17's ungated arm: finish accepts any answer (errors are still recorded)."""
    from .agent import Tool, run_agent
    from .panel import _obj
    t0 = time.perf_counter()
    rep = _report(city, slug)
    desk = desk_for(rep)
    final: dict = {}
    attempts: list[dict] = []

    def read_receipt(receipt: str) -> dict:
        if receipt not in desk.data:
            return {"error": f"no receipt {receipt}; receipts: {sorted(desk.data)}"}
        meta = next(r for r in desk.receipts if r["id"] == receipt)
        text = json.dumps(desk.data[receipt], default=str)
        return {"receipt": receipt, "tool": meta["tool"], "summary": meta["summary"],
                "data": json.loads(text) if len(text) <= 7000 else text[:7000] + " ...(truncated)"}

    def mechanisms() -> dict:
        row = _extra("experiment_T15.json", "runs", slug)
        if not row:
            return {"error": "the miner has not run at this corner"}
        from .miner import SPEC
        data = {"confirmed": row["confirmed"], "proposed": row.get("proposals"), "split": SPEC["split"]}
        rid = desk.record("mechanisms", data, ["NML-Bench T15 (validation/BENCH.md)"],
                          ["explored before the split, confirmed once on later years, Holm over every proposal"],
                          time.perf_counter(), f"{len(row['confirmed'])} mechanisms confirmed on later years")
        return {"receipt": rid, **data}

    def site_check() -> dict:
        row = _extra("experiment_T16.json", "rows", slug)
        if not row or not row.get("answers"):
            return {"error": "no site check for this corner"}
        data = {"answers": {a: v["gated"] for a, v in row["answers"].items()}, "truth": row.get("truth")}
        rid = desk.record("site_check", data, ["state orthophoto; Muse Spark + SAM 3.1 (NML-Bench T16)"],
                          ["present only when SAM 3.1 confirms Muse Spark's point"], time.perf_counter(),
                          "what the aerial photo shows")
        return {"receipt": rid, **data}

    def find_corners(field: str, value: str) -> dict:
        from .pages import DOCS
        f = DOCS / "data" / city / "index.json"
        idx = json.loads(f.read_text()) if f.exists() else {"corners": []}
        hits = [c for c in idx.get("corners", []) if str(c.get(field, "")).lower() == value.lower()][:20]
        rid = desk.record("find_corners", {"field": field, "value": value, "corners": hits}, [f"docs/data/{city}/index.json"],
                          ["exact match on the index field"], time.perf_counter(), f"{len(hits)} corners")
        return {"receipt": rid, "corners": hits}

    def finish(answer: str, claims: list[dict]) -> dict:
        errors = engineer.check_claims(claims, desk) + engineer.check_summary(answer, desk)
        attempts.append({"answer": answer, "claims": claims, "errors": errors})
        if errors and gated:
            return {"error": "refused by the claim checker", "errors": errors[:10]}
        final.update(answer=answer, claims=claims)
        return {"ok": True}

    txt = {"type": "string"}
    claim = {"type": "array", "items": _obj({"text": txt, "receipt": txt}, ["text", "receipt"]), "maxItems": 5}
    tools = [Tool("read_receipt", "The data behind one of the corner's receipts: "
                  + "; ".join(f"{r['id']} {r['tool']}" for r in desk.receipts), _obj({"receipt": txt}, ["receipt"]), read_receipt),
             Tool("mechanisms", "Crash mechanisms at this corner confirmed on later years.", _obj({}, []), mechanisms),
             Tool("site_check", "What the aerial photo shows at this corner (SAM 3.1-confirmed).", _obj({}, []), site_check),
             Tool("find_corners", "Corners of the city whose index field equals a value (e.g. plan_gap true).",
                  _obj({"field": txt, "value": txt}, ["field", "value"]), find_corners),
             Tool("finish", "Answer with at most 5 claims, each citing a receipt.", _obj({"answer": txt, "claims": claim},
                                                                                       ["answer", "claims"]), finish)]
    if hasattr(client, "force_finish_after"):
        client.force_finish_after = max(client.force_finish_after, 8)
    run = run_agent(client, MODELS["open_label"], INSTRUCTIONS,
                    f"Corner: {rep['junction']['name']}. Question: {question[:500]}", tools, 10, budget_usd,
                    effort="low", tag=f"ask {slug[:30]}", escalate_after=3)
    refused = [{"text": c.get("text"), "errors": [e for e in a["errors"] if e.startswith(f"claim {k}:")]}
               for a in attempts if a["errors"] for k, c in enumerate(a["claims"], 1)
               if any(e.startswith(f"claim {k}:") for e in a["errors"])]
    shown_errors = engineer.check_claims(final.get("claims", []), desk) + engineer.check_summary(final.get("answer") or "", desk)
    return {"question": question, "corner": slug, "answer": final.get("answer"), "claims": final.get("claims", []),
            "shown_errors": shown_errors, "gated": gated,
            "refused": refused, "receipts": desk.receipts, "usd": round(run.usd, 5), "turns": run.turns,
            "stopped": run.stopped, "seconds": round(time.perf_counter() - t0, 2),
            "tool_calls": [{"tool": s.tool, "seconds": round(getattr(s, "seconds", 0) or 0, 2)} for s in run.steps]}
