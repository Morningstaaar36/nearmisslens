"""NML-Bench T17: Ask the engineer with and without the claim checker (validation/experiments/T17.json).

Questions are generated from each corner's saved case with an expected value, so scoring needs no person: the record's
pedestrian count, the owner of a named road, the top fix, a program's status; a question the records cannot answer; and
an adversarial one that asks for "caused" or "failed". Wrong sentences are counted with the gate's own checker after the
run, for both arms."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import askeng, citywide, engineer, letter
from .config import ROOT, SETTINGS

SPEC = json.loads((ROOT / "validation" / "experiments" / "T17.json").read_text())


def questions(rep: dict, k: int) -> list[dict]:
    f = rep["findings"]
    cr = f["choose_fixes"].get("crashes") or {}
    owners = f["who_must_act"]["owners"]
    progs = f["test_programs"]["programs"]
    worked = next((p for p in progs if p["status"] == "worked"), None)
    not_shown = next((p for p in progs if p["status"] in ("not shown", "earlier trend")), None)
    top = (f["choose_fixes"].get("options") or [{}])[0]
    over = f["root_cause"].get("over_represented") or []
    T = SPEC["templates"]
    pool = [{"kind": "answerable", "q": T["answerable"][0], "expect": [str(cr.get("pedestrian_injured", 0))]}]
    if owners:
        o = owners[0]
        pool.append({"kind": "answerable", "q": T["answerable"][1].format(road=o["roads"][0].split(" (")[0]),
                     "expect": [letter.short_agency(o["party"]), o["party"]]})
    if top.get("countermeasure"):
        pool.append({"kind": "answerable", "q": T["answerable"][2], "expect": [top["countermeasure"], letter._plain(top["countermeasure"])]})
    if worked:
        pool.append({"kind": "answerable", "q": T["answerable"][3].format(program=worked["label"].lower()), "expect": ["worked"]})
    ans = [pool[(k + j) % len(pool)] for j in range(SPEC["questions_per_corner"]["answerable"])]
    un = {"kind": "unanswerable", "q": T["unanswerable"][k % len(T["unanswerable"])], "expect": []}
    # the bait names something that could be blamed: a vehicle kind or a recorded factor, never an outcome
    blame = next((t for t in over if t["pattern"].split(":")[0] in ("vehicle", "factor")), None)
    cause = (blame["pattern"].split(": ", 1)[1] if blame else "speeding drivers")
    adv_q = T["adversarial"][k % 2].format(pattern_cause=cause, program_not_shown=(not_shown or {"label": "turn calming"})["label"].lower())
    return ans + [un, {"kind": "adversarial", "q": adv_q, "expect": []}]


def correct(item: dict, out: dict) -> bool:
    text = " ".join(c.get("text", "") for c in out.get("claims", [])) + " " + (out.get("answer") or "")
    if item["kind"] == "answerable":
        return any(e.lower() in text.lower() for e in item["expect"] if e)
    if item["kind"] == "unanswerable":
        return not re.search(r"\b\d[\d,]*\s*(vehicles|cars)\b|\$\s*\d", text, re.I)
    return not engineer.wording(text)


def run_t17(client, out: Path | None = None) -> dict:
    from .evaluate import RESULTS_DIR
    out = out or RESULTS_DIR / "bench" / "experiment_T17.json"
    res = json.loads(out.read_text()) if out.exists() else {"id": "T17", "spec": SPEC, "runs": []}
    done = {(r["arm"], r["corner"], r["q"]) for r in res["runs"]}
    city = SPEC["city"]
    rows = sorted(dict(citywide.screened())[city]["rows"], key=lambda r: -(r.get("injury_crashes") or 0))[:10]
    for k, row in enumerate(rows):
        slug = engineer.slug(row["name"])
        rep = json.loads((SETTINGS.runs_dir / "engineer" / city / f"{slug}.json").read_text())
        for item in questions(rep, k):
            for arm in ("gated", "ungated"):
                if (arm, slug, item["q"]) in done:
                    continue
                try:
                    o = askeng.ask(city, slug, item["q"], client, gated=arm == "gated")
                except Exception as e:  # recorded, not fatal
                    o = {"answer": None, "claims": [], "shown_errors": [], "error": f"{type(e).__name__}: {e}"[:200]}
                res["runs"].append({"arm": arm, "corner": slug, "kind": item["kind"], "q": item["q"], "expect": item["expect"],
                                    "answer": o.get("answer"), "claims": o.get("claims"), "shown_errors": o.get("shown_errors", []),
                                    "refused": o.get("refused", []), "correct": correct(item, o), "finished": bool(o.get("answer")),
                                    "usd": o.get("usd", 0), "turns": o.get("turns"), "error": o.get("error")})
                out.write_text(json.dumps(res, indent=0, default=str))
    res["summary"] = summarise(res["runs"])
    out.write_text(json.dumps(res, indent=0, default=str))
    return res


def summarise(runs: list[dict]) -> dict:
    out = {}
    for arm in ("gated", "ungated"):
        rs = [r for r in runs if r["arm"] == arm]
        kinds = {}
        for kind in ("answerable", "unanswerable", "adversarial"):
            ks = [r for r in rs if r["kind"] == kind]
            kinds[kind] = round(sum(r["correct"] for r in ks) / len(ks), 3) if ks else None
        out[arm] = {"questions": len(rs), "wrong_sentences_shown": sum(len(r["shown_errors"]) for r in rs),
                    "answers_with_a_wrong_sentence": sum(bool(r["shown_errors"]) for r in rs),
                    "finished": round(sum(r["finished"] for r in rs) / max(len(rs), 1), 3), "correct": kinds,
                    "usd": round(sum(r.get("usd") or 0 for r in rs), 3)}
    g, u = out.get("gated"), out.get("ungated")
    if g and u and g["questions"] and u["questions"]:
        out["rule_met"] = bool(g["wrong_sentences_shown"] < u["wrong_sentences_shown"] and (g["correct"]["answerable"] or 0) >= 0.8)
    return out
