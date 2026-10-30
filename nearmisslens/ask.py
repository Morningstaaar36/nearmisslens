"""Intake agent: a resident's complaint, spoken or typed, is checked against a junction's audit. Muse Wonder reads the
hotspots, looks at the video evidence and answers supported, not observed or unclear. A checker inside the finish tool
rejects any answer that cites a hotspot whose conflicts do not involve the road users named, a countermeasure the audit
did not keep, or a number that is not in the data."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from . import panel
from .agent import MEDIA_KEY, Tool, run_agent
from .meta_client import MetaClient
from .voice import USERS

MODEL = "muse-wonder-1.0"
MAX_TURNS = 10
BUDGET_USD = 0.25
VERDICTS = ("supported", "not_observed", "unclear")
INSTRUCTIONS = (
    "You are the intake officer of a road-safety team. A resident has complained about one junction. Decide, from the "
    "junction's audit only, whether the measured near-misses support the complaint. Read the site summary and the "
    "hotspots; call evidence for a hotspot to see a frame of its worst reviewed conflict and the countermeasure "
    "illustration. Then call finish once with: verdict 'supported' (a hotspot's dominant conflicts involve exactly the "
    "road users the complaint names, and do not contradict its movement or approach), 'not_observed' (the complaint "
    "is specific but no hotspot shows it), or 'unclear' (the complaint names no road users or is not about near-misses); "
    "the hotspot rank (0 unless supported); road_users as named in the complaint (vehicle, two_wheeler, pedestrian); "
    "the countermeasure CMF ids you recommend (only ones the audit kept for that hotspot; none otherwise); and a short "
    "answer to the resident that cites only numbers from the audit. If finish is rejected, read the errors and fix "
    "them.")


def _frame(clip: str, out_dir: Path, width: int = 960) -> Path | None:
    """The middle frame of an event clip as a JPEG, for the model to look at."""
    clip_path = Path(clip)
    if not clip_path.exists():
        return None
    out = out_dir / f"{clip_path.stem}.jpg"
    if not out.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-3.5", "-i", str(clip_path), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", str(out)], check=False)
    return out if out.exists() else None


def tools(facts: dict, memo_md: str, cmf: pd.DataFrame, frames_dir: Path, checked: bool = True,
          record: list | None = None) -> tuple[list[Tool], panel.Grounding]:
    g = panel.Grounding(facts, memo_md)
    reads = panel.read_tools(facts, cmf, g)
    by_rank = {f["rank"]: f for f in facts["findings"]}

    def evidence(rank: int) -> dict:
        f = by_rank.get(rank)
        if f is None:
            return {"error": f"hotspot {rank} does not exist (hotspots: {sorted(by_rank)})"}
        images, review = [], None
        verdicts = (f.get("verification") or {}).get("verdicts") or []
        if verdicts:
            v = verdicts[0]
            review = {k: v.get(k) for k in ("measure", "value", "cls_1", "cls_2", "type", "real_conflict",
                                            "evasive_action", "who_yielded", "reason")}
            frame = _frame(v.get("clip", ""), frames_dir)
            if frame:
                images.append(frame)
        ill = f.get("illustration") or {}
        if ill.get("image") and Path(ill["image"]).exists():
            images.append(Path(ill["image"]))
        g.add(review or {})
        return {"rank": rank, "worst_reviewed_conflict": review, "illustration": ill.get("countermeasure"),
                "illustration_check_passed": ill.get("check_passed"), MEDIA_KEY: [str(p) for p in images]}

    def check(verdict: str, rank: int, road_users: list[str], cmf_ids: list[str], answer: str) -> list[str]:
        errors = []
        if verdict == "supported":
            f = by_rank.get(rank)
            if f is None:
                errors.append(f"hotspot {rank} does not exist (hotspots: {sorted(by_rank)})")
            elif set(road_users) != set(f["dominant"]["pair"]):
                errors.append(f"hotspot {rank}'s dominant conflicts are {' and '.join(f['dominant']['pair'])}, "
                              f"not {' and '.join(sorted(set(road_users))) or 'no road users'}")
            for c in cmf_ids:
                bad = g.recommendation(rank, c)
                if bad:
                    errors.append(bad)
        else:
            if rank:
                errors.append(f"verdict {verdict} must use hotspot 0")
            if cmf_ids:
                errors.append(f"verdict {verdict} cannot recommend countermeasures")
        if verdict == "unclear" and road_users:
            errors.append("verdict unclear means the complaint names no road users; use not_observed")
        errors += g.text(answer)
        return errors

    def finish(verdict: str, rank: int, road_users: list[str], cmf_ids: list[str], answer: str) -> dict:
        errors = check(verdict, rank, road_users, cmf_ids, answer)
        if record is not None:
            record.append({"verdict": verdict, "rank": rank, "road_users": road_users, "cmf_ids": cmf_ids,
                           "answer": answer, "errors": errors})
        if errors and checked:
            return {"error": "rejected by the grounding checker", "errors": errors}
        return {"ok": True}

    finish_tool = Tool("finish", "Submit the verdict on the complaint.", panel._obj({
        "verdict": {"type": "string", "enum": list(VERDICTS)}, "rank": {"type": "integer"},
        "road_users": {"type": "array", "items": {"type": "string", "enum": list(USERS)}},
        "cmf_ids": {"type": "array", "items": {"type": "string"}}, "answer": {"type": "string"}},
        ["verdict", "rank", "road_users", "cmf_ids", "answer"]), finish)
    look = Tool("evidence", "A frame of the hotspot's worst conflict reviewed on video, Muse Spark's verdict on it, and "
                            "the countermeasure illustration (images are attached).",
                panel._obj({"rank": {"type": "integer"}}, ["rank"]), evidence)
    return reads + [look, finish_tool], g


def answer(client: MetaClient, complaint: str, facts: dict, memo_md: str, cmf: pd.DataFrame, frames_dir: Path,
           tag: str, checked: bool = True, effort: str = "low", model: str = MODEL, budget_usd: float = BUDGET_USD) -> dict:
    """Run the intake agent on one complaint. checked=False is the ablation: finish accepts anything, and the
    checker's verdict on the submitted answer is only recorded."""
    record: list = []
    ts, _ = tools(facts, memo_md, cmf, frames_dir, checked=checked, record=record)
    run = run_agent(client, model, INSTRUCTIONS, f"Complaint: {complaint}", ts, MAX_TURNS, budget_usd, effort=effort,
                    tag=tag, summaries=model.startswith("muse-wonder"), escalate_after=3)
    final = next((r for r in reversed(record) if not r["errors"]), record[-1] if record else None)
    if not checked and record:
        final = record[-1]
    return {"complaint": complaint, "model": model, "result": final, "stopped": run.stopped, "turns": run.turns,
            "usd": round(run.usd, 4), "refusals": run.refusals, "timeline": run.timeline(),
            "escalated": run.stopped == "escalated"}


def truth(c: dict, facts: dict) -> tuple[str, set]:
    """Expected verdict and hotspots for a benchmark complaint built from slots: supported by every hotspot whose
    dominant pair is the complaint's road users and whose movements/approaches do not contradict a stated slot."""
    if not c.get("pair"):
        return "unclear", set()
    ranks = set()
    for f in facts["findings"]:
        d = f["dominant"]
        if set(c["pair"]) != set(d["pair"]):
            continue
        if c.get("movement") and not d.get("movements", {}).get(c["movement"]):
            continue
        if c.get("approach") and not d.get("approaches", {}).get(c["approach"]):
            continue
        ranks.add(f["rank"])
    return ("supported", ranks) if ranks else ("not_observed", set())


def load(split_source: str, runs_dir: Path) -> tuple[dict, str]:
    src = runs_dir / "audit" / split_source
    return json.loads((src / "facts.json").read_text()), (src / "memo.md").read_text()
