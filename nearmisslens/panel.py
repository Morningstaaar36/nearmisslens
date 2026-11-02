"""Review panel: three Muse agents argue an audit's recommendations, and a deterministic checker holds every claim
to the data.

The Proposer (Muse Spark) picks countermeasures per hotspot, the Skeptic (Muse Spark) objects with evidence, and the
Arbiter (Muse Wonder) decides and writes the memo. An agent can only finish when the checker accepts its output: every
hotspot and CMF ID must exist in the audit, a recommended CMF must be one the audit kept for that hotspot, and every
number in the text must appear in the audit, its memo or a tool result the agent read. Rejected attempts are kept."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import pandas as pd

from .agent import Tool, run_agent
from .meta_client import MetaClient
from .config import MODELS

PROPOSER_MODEL = MODELS["reader"]
SKEPTIC_MODEL = MODELS["reader"]
ARBITER_MODEL = MODELS["large"]
BUDGET_USD = {"proposer": 0.05, "skeptic": 0.05, "judge": 0.8}
MAX_TURNS = 14
MAX_OUTPUT_TOKENS = 16000
MAX_PER_HOTSPOT = 2

DECIMAL_COMMA = re.compile(r"(?<![\d,])(\d+),(\d{1,2})(?!\d)")


def normalise_decimals(text: str) -> str:
    """'185,7' (decimal comma, as in Spanish or French answers) becomes '185.7'; '1,234' is left as a thousands
    separator."""
    return DECIMAL_COMMA.sub(r"\1.\2", text)


NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
HOTSPOT_REF = re.compile(r"\bhotspot\s*#?\s*(\d+)", re.I)
CMF_REF = re.compile(r"\bCMF\s*(?:Clearinghouse\s*)?(?:ID\s*)?#?\s*(\d{3,6})\b")
CMF_FIELDS = ["crfid", "name", "cmf", "crf_pct", "stars", "crash_type", "severity", "control", "area", "country",
              "citation"]

_COMMON = ("Use only numbers that appear in tool results, and cite CMF IDs as 'CMF <id>'. Finish with finish; if it "
           "returns an error, correct every listed problem and call finish again.")
PROPOSER_INSTRUCTIONS = (
    "You are the Proposer on a road-safety review panel. An automated audit of drone video found conflict hotspots "
    "and, for each, FHWA Proven Safety Countermeasures with CMF Clearinghouse estimates that fit the observed "
    "conflicts. Read site_summary, then hotspot for each rank. Recommend one or two countermeasures for every hotspot "
    "that has any, chosen from that hotspot's countermeasures list, with a reason tied to its evidence: conflict type "
    "and road users, movements, signal state on entry, the video review and the CMF's rating and crash type. " + _COMMON)
SKEPTIC_INSTRUCTIONS = (
    "You are the Skeptic on a road-safety review panel. Challenge the Proposer's recommendations with evidence from "
    "the tools: few events or wide confidence intervals, conflicts the video review judged not real, CMFs that are "
    "unrated or estimated for other crash types, severities, area types or countries (look them up with cmf), and "
    "notes such as a missing two-wheeler crash type. Mark an objection blocking only when the evidence shows the "
    "countermeasure would not address the hotspot. Use crfid '' for an objection to the hotspot as a whole. " + _COMMON)
ARBITER_INSTRUCTIONS = (  # wording unchanged since T5: the replay cache is keyed on it
    "You are the Judge on a road-safety review panel. Accept or reject every proposal, weighing the objections against "
    "the tool results. Then write a markdown memo for a city traffic engineer, at most 250 words: what was observed, "
    "which countermeasures to consider first and why, and the limits (surrogate measures from a short observation, "
    "not crash predictions; a qualified traffic engineer must review any design). " + _COMMON)


def _obj(props: dict, req: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


def _array(props: dict) -> dict:
    return {"type": "array", "items": _obj(props, list(props))}


def _value(token: str) -> float:
    return float(token.replace(",", ""))


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def numbers_in(obj) -> list[float]:
    """Every number in a JSON-like object, including numbers written inside strings."""
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in numbers_in(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in numbers_in(v)]
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [abs(float(obj))] if obj == obj else []
    return [_value(t) for t in NUMBER.findall(str(obj))]


class Grounding:
    """What the panel may claim: hotspot ranks, the CMF IDs the audit mentions, the countermeasures it kept per
    hotspot, and the numbers in the audit, its memo and any tool result shown to an agent."""

    def __init__(self, facts: dict, memo_md: str):
        self.ranks = {f["rank"] for f in facts["findings"]}
        self.kept = {f["rank"]: {c["crfid"]: c for c in f["countermeasures"]} for f in facts["findings"]}
        self.cited = {c for f in facts["findings"] for c in self.kept[f["rank"]]}
        self.cited |= {r["crfid"] for f in facts["findings"] for r in f["rejected"] if r.get("crfid")}
        self.known: set[float] = set()
        self.add(facts)
        self.add(memo_md)

    def add(self, obj) -> None:
        self.known.update(numbers_in(obj))

    def _number_ok(self, token: str) -> bool:
        v, tol = _value(token), 0.5 * 10 ** -_decimals(token) + 1e-9
        return any(abs(k - v) <= tol for k in self.known)

    def text(self, text: str) -> list[str]:
        """Errors for the reading of the text with fewer of them: commas as written, or '185,7' as a decimal comma
        (so a list like 'hotspots 1,2' is not misread as 1.2)."""
        a, b = self._text(text), self._text(normalise_decimals(text))
        return a if len(a) <= len(b) else b

    def _text(self, text: str) -> list[str]:
        errors = [f"hotspot {n} does not exist (hotspots: {sorted(self.ranks)})"
                  for n in sorted({int(m) for m in HOTSPOT_REF.findall(text)} - self.ranks)]
        errors += [f"CMF {i} is not in this audit" for i in sorted(set(CMF_REF.findall(text)) - self.cited)]
        ids = set(CMF_REF.findall(text))
        errors += [f"number {t} does not appear in the audit or the tool results" for t in dict.fromkeys(NUMBER.findall(text))
                   if t not in ids and not self._number_ok(t)]
        return errors

    def recommendation(self, rank: int, crfid: str) -> str | None:
        if rank not in self.ranks:
            return f"hotspot {rank} does not exist (hotspots: {sorted(self.ranks)})"
        if crfid not in self.kept[rank]:
            return f"CMF {crfid} is not among hotspot {rank}'s countermeasures ({', '.join(self.kept[rank]) or 'none'})"
        return None


def check_proposals(g: Grounding, recommendations: list[dict]) -> list[str]:
    errors = []
    seen = set()
    for r in recommendations:
        bad = g.recommendation(r["rank"], r["crfid"])
        if bad:
            errors.append(bad)
        if (r["rank"], r["crfid"]) in seen:
            errors.append(f"CMF {r['crfid']} is recommended twice for hotspot {r['rank']}")
        seen.add((r["rank"], r["crfid"]))
        errors += [f"hotspot {r['rank']}, CMF {r['crfid']}: {e}" for e in g.text(r["reason"])]
    per = pd.Series([r["rank"] for r in recommendations], dtype=int).value_counts()
    errors += [f"hotspot {k} has {n} recommendations; at most {MAX_PER_HOTSPOT}" for k, n in per.items() if n > MAX_PER_HOTSPOT]
    errors += [f"hotspot {k} has countermeasures but no recommendation" for k in sorted(g.ranks)
               if g.kept[k] and k not in per.index]
    return errors


def check_objections(g: Grounding, proposals: list[dict], objections: list[dict]) -> list[str]:
    proposed = {(p["rank"], p["crfid"]) for p in proposals}
    errors = []
    for o in objections:
        if o["rank"] not in g.ranks:
            errors.append(f"hotspot {o['rank']} does not exist")
        elif o["crfid"] and (o["rank"], o["crfid"]) not in proposed:
            errors.append(f"CMF {o['crfid']} was not proposed for hotspot {o['rank']}")
        errors += [f"objection to hotspot {o['rank']}: {e}" for e in g.text(o["objection"])]
    return errors


def check_decisions(g: Grounding, proposals: list[dict], decisions: list[dict], memo: str) -> list[str]:
    proposed = [(p["rank"], p["crfid"]) for p in proposals]
    decided = [(d["rank"], d["crfid"]) for d in decisions]
    errors = [f"no decision on CMF {c} for hotspot {r}" for r, c in proposed if (r, c) not in decided]
    errors += [f"CMF {c} for hotspot {r} was not proposed" for r, c in decided if (r, c) not in proposed]
    errors += [f"CMF {c} for hotspot {r} is decided more than once" for r, c in set(decided) if decided.count((r, c)) > 1]
    for d in decisions:
        errors += [f"decision on hotspot {d['rank']}, CMF {d['crfid']}: {e}" for e in g.text(d["reason"])]
    if not memo.strip():
        errors.append("the memo is empty")
    errors += [f"memo: {e}" for e in g.text(memo)]
    return errors


def read_tools(facts: dict, cmf: pd.DataFrame, g: Grounding) -> list[Tool]:
    """Read-only views of the audit; everything an agent reads becomes citable."""
    by_rank = {f["rank"]: f for f in facts["findings"]}
    cmf_by_id = cmf.set_index("crfid")

    def shown(result: dict) -> dict:
        g.add(result)
        return result

    def summary() -> dict:
        hot = [{"rank": f["rank"], "x_m": f["x"], "y_m": f["y"], "events": f["events"], "users": f["users"],
                "rate_per_1000": f["rate_per_1000"], "ci95": f["ci95"], "dominant_pair": f["dominant"]["pair"],
                "dominant_type": f["dominant"]["type"], "countermeasures": len(f["countermeasures"]),
                "video_reviewed": bool(f.get("verification"))} for f in facts["findings"]]
        return shown({k: v for k, v in facts.items() if k != "findings"} | {"hotspots": hot})

    def hotspot(rank: int) -> dict:
        if rank not in by_rank:
            return {"error": f"hotspot {rank} does not exist (hotspots: {sorted(by_rank)})"}
        return shown(by_rank[rank])

    def lookup(crfid: str) -> dict:
        if crfid not in cmf_by_id.index:
            return {"error": f"CMF {crfid} is not in the CMF Clearinghouse database"}
        row = cmf_by_id.loc[[crfid]].iloc[0]
        return shown({"crfid": crfid} | {k: (None if pd.isna(row[k]) else row[k]) for k in CMF_FIELDS[1:]})

    return [
        Tool("site_summary", "Observation length, road users, control, conflict counts, thresholds and the ranked "
                             "hotspots.", _obj({}, []), summary),
        Tool("hotspot", "Everything the audit found at one hotspot: severity, examples, movements, signal state on "
                        "entry, kept and rejected countermeasures, video review and illustration.",
             _obj({"rank": {"type": "integer"}}, ["rank"]), hotspot),
        Tool("cmf", "The CMF Clearinghouse record for a CMF ID: estimate, rating, crash type, severity, area, country "
                    "and study citation.", _obj({"crfid": {"type": "string"}}, ["crfid"]), lookup),
    ]


def _stage(client: MetaClient, model: str, instructions: str, task: str, tools: list[Tool], finish: Tool, role: str,
           tag: str, checked: bool = True) -> dict:
    attempts: list[dict] = []
    inner = finish.fn

    def record_attempt(**kwargs):
        result = inner(**kwargs)
        attempts.append({"arguments": kwargs, "errors": result.get("errors", [])})
        return result

    run = run_agent(client, model, instructions, task, tools + [Tool(finish.name, finish.description, finish.parameters,
                                                                     record_attempt)],
                    MAX_TURNS, BUDGET_USD[role], effort="medium", tag=f"{tag} {role}", max_output_tokens=MAX_OUTPUT_TOKENS)
    passed = [a for a in attempts if not a["errors"]]
    if not checked:  # ablation: the first submission stands; its checker errors are only recorded
        accepted = run.stopped == "finish_tool" and bool(attempts)
        return {"role": role, "model": model, "accepted": accepted, "stopped": run.stopped, "turns": run.turns,
                "usd": round(run.usd, 4), "rejected_attempts": [],
                "ungrounded": attempts[-1]["errors"] if attempts else [],
                "output": attempts[-1]["arguments"] if accepted else None, "decision_log": run.decision_log()}
    accepted = run.stopped == "finish_tool" and bool(passed)
    return {"role": role, "model": model, "accepted": accepted, "stopped": run.stopped, "turns": run.turns,
            "usd": round(run.usd, 4), "rejected_attempts": [a for a in attempts if a["errors"]],
            "output": passed[0]["arguments"] if accepted else None, "decision_log": run.decision_log()}


def _finish(check: Callable[..., list[str]], checked: bool = True) -> Callable[..., dict]:
    def fn(**kwargs):
        errors = check(**kwargs)
        if not checked:
            return {"ok": True, "errors": errors}
        return {"error": "rejected by the grounding checker", "errors": errors} if errors else {"ok": True}
    return fn


def run_panel(client: MetaClient, facts: dict, memo_md: str, cmf: pd.DataFrame, tag: str, checked: bool = True) -> dict:
    """Proposer, Skeptic and Arbiter. checked=False is the NML-Bench T5 ablation: every finish is accepted as submitted
    and the checker's errors are only recorded (stage["ungrounded"])."""
    g = Grounding(facts, memo_md)
    tools = read_tools(facts, cmf, g)
    rec = {"rank": {"type": "integer"}, "crfid": {"type": "string"}, "reason": {"type": "string"}}
    proposer = _stage(client, PROPOSER_MODEL, PROPOSER_INSTRUCTIONS, "Propose countermeasures. Start with site_summary.",
                      tools, Tool("finish", "Submit the recommendations.", _obj({"recommendations": _array(rec)},
                                                                                ["recommendations"]),
                                  _finish(lambda recommendations: check_proposals(g, recommendations), checked)),
                      "proposer", tag, checked)
    stages = [proposer]
    if not proposer["accepted"]:
        return {"status": "proposer did not finish", "stages": stages}
    proposals = [{**r, "psc": g.kept.get(r["rank"], {}).get(r["crfid"], {}).get("psc", "not kept by the audit")}
                 for r in proposer["output"]["recommendations"]]
    obj = {"rank": {"type": "integer"}, "crfid": {"type": "string"}, "objection": {"type": "string"},
           "blocking": {"type": "boolean"}}
    skeptic = _stage(client, SKEPTIC_MODEL, SKEPTIC_INSTRUCTIONS,
                     f"Proposals:\n{json.dumps(proposals, indent=1)}\nObject where the evidence warrants it.",
                     tools, Tool("finish", "Submit the objections (an empty list if none).",
                                 _obj({"objections": _array(obj)}, ["objections"]),
                                 _finish(lambda objections: check_objections(g, proposals, objections), checked)),
                     "skeptic", tag, checked)
    stages.append(skeptic)
    if not skeptic["accepted"]:
        return {"status": "skeptic did not finish", "stages": stages, "proposals": proposals}
    objections = skeptic["output"]["objections"]
    dec = {"rank": {"type": "integer"}, "crfid": {"type": "string"}, "accept": {"type": "boolean"},
           "reason": {"type": "string"}}
    arbiter = _stage(client, ARBITER_MODEL, ARBITER_INSTRUCTIONS,
                   f"Proposals:\n{json.dumps(proposals, indent=1)}\nObjections:\n{json.dumps(objections, indent=1)}\n"
                   "Decide every proposal and write the memo.",
                   tools, Tool("finish", "Submit the decisions and the memo.",
                               _obj({"decisions": _array(dec), "memo": {"type": "string"}}, ["decisions", "memo"]),
                               _finish(lambda decisions, memo: check_decisions(g, proposals, decisions, memo), checked)),
                   "judge", tag, checked)  # the role label (and the prompt's wording) are kept: saved results and the
    stages.append(arbiter)                    # replay cache are keyed on them
    if not arbiter["accepted"]:
        return {"status": "judge did not finish", "stages": stages, "proposals": proposals, "objections": objections}
    return {"status": "complete", "stages": stages, "proposals": proposals, "objections": objections,
            "decisions": arbiter["output"]["decisions"], "memo": arbiter["output"]["memo"],
            "usd": round(sum(s["usd"] for s in stages), 4),
            "caught": sum(len(a["errors"]) for s in stages for a in s["rejected_attempts"]),
            "ungrounded": sum(len(s.get("ungrounded", [])) for s in stages)}


def panel_markdown(result: dict, title: str) -> str:
    lines = [f"# Review panel: {title}", "", f"Status: {result['status']}.", ""]
    if result.get("decisions"):
        psc = {(p["rank"], p["crfid"]): p["psc"] for p in result["proposals"]}
        lines += ["| Hotspot | Countermeasure | CMF | Decision | Reason |", "|---|---|---|---|---|"]
        lines += [f"| {d['rank']} | {psc[(d['rank'], d['crfid'])]} | {d['crfid']} | "
                  f"{'accept' if d['accept'] else 'reject'} | {d['reason']} |" for d in result["decisions"]]
        lines += ["", "## Arbiter's memo", "", result["memo"].strip(), ""]
    if result.get("objections"):
        lines += ["## Skeptic's objections", ""]
        lines += [f"- Hotspot {o['rank']}{', CMF ' + o['crfid'] if o['crfid'] else ''}"
                  f"{' (blocking)' if o['blocking'] else ''}: {o['objection']}" for o in result["objections"]]
        lines.append("")
    lines += ["## Grounding checker", ""]
    for s in result["stages"]:
        lines.append(f"- {s['role']} ({s['model']}): {'accepted' if s['accepted'] else s['stopped']} after "
                     f"{s['turns']} turns, ${s['usd']:.4f}; {len(s['rejected_attempts'])} rejected attempt(s)")
        for a in s["rejected_attempts"]:
            lines += [f"  - rejected: {e}" for e in a["errors"]]
    return "\n".join(lines) + "\n"


def write(result: dict, out: Path, title: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "panel.json").write_text(json.dumps(result, indent=1, default=str))
    (out / "panel.md").write_text(panel_markdown(result, title))
