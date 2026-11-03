"""Program review: an agency's list of proposed safety projects, each reviewed before money is committed (the
"Before you commit" review: Muse Spark investigates, code appraises, Muse Spark Open argues against), then ranked by
code into one program memo: what to build first within a budget, what to compare with a better-supported fix, what
needs a study because no evidence covers it, and what to reconsider, each with its memo.

Code does all of the ranking. No model sees the whole list, so no model can trade one corner against another; the
ranking is the reviews' numbers, sorted."""
from __future__ import annotations

import csv
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import review as rv_mod
from .config import SETTINGS, portable

MAX_ITEMS = 25
EXAMPLES = Path(__file__).resolve().parent.parent / "validation" / "examples" / "programs.json"
WORKERS = 3
GROUPS = (  # program groups, in the order the memo gives them
    ("build", "Build: the evidence supports these here", ("proceed",)),
    ("site_check", "Build after a site check", ("proceed_after_site_check",)),
    ("compare", "Compare first: another proven fix would avoid at least twice as many crashes",
     ("compare_alternative",)),
    ("parts", "Decide part by part", ("mixed",)),
    ("study", "Not covered by the evidence: fund a before-and-after study, not a promise", ("outside_evidence",)),
    ("reconsider", "Reconsider", ("reconsider",)),
)
FUNDABLE = ("proceed", "proceed_after_site_check")


def example(pid: str) -> dict:
    """A saved real program list (validation/examples/programs.json), by id."""
    data = json.loads(EXAMPLES.read_text())
    for p in data["programs"]:
        if p["id"] == pid:
            return {**p, "asof": p.get("asof") or data.get("asof")}
    raise ValueError(f"no program {pid!r}; ids: {', '.join(p['id'] for p in data['programs'])}")


def read_list(text: str) -> list[dict]:
    """A program list as people keep one: a JSON list (of strings or {"text", "cost_usd", "city"}), a CSV with a
    "text" (or "project"/"proposal") column and optional "cost_usd"/"city" columns, or one proposal per line."""
    text = (text or "").strip()
    if not text:
        return []
    if text[0] in "[{":
        js = json.loads(text)
        js = js.get("projects", js) if isinstance(js, dict) else js
        return [{"text": x} if isinstance(x, str) else dict(x) for x in js][:MAX_ITEMS]
    first = text.splitlines()[0].lower()
    if "," in first and re.search(r"\b(text|project|proposal)\b", first):
        rows = list(csv.DictReader(io.StringIO(text)))
        key = next(k for k in rows[0] if k and k.strip().lower() in ("text", "project", "proposal"))
        out = []
        for r in rows:
            item = {"text": (r.get(key) or "").strip()}
            cost = (r.get("cost_usd") or r.get("cost") or "").replace("$", "").replace(",", "").strip()
            if cost:
                item["cost_usd"] = float(cost)
            if r.get("city"):
                item["city"] = r["city"].strip()
            if item["text"]:
                out.append(item)
        return out[:MAX_ITEMS]
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", x).strip() for x in text.splitlines()]
    return [{"text": x} for x in lines if len(x) > 8][:MAX_ITEMS]


def _proposal_text(item: dict) -> str:
    t = item["text"].strip()
    if item.get("cost_usd") and "$" not in t:
        t += f" (estimated cost ${item['cost_usd']:,.0f})"
    return t


def review_all(items: list[dict], city: str, client=None, letter_client=None, open_client=None,
               budget_usd: float = 0.50, workers: int = WORKERS, done: dict | None = None,
               reviewer=None, on_result=None) -> list[dict]:
    """Each proposal reviewed (a few at a time); a proposal already reviewed (`done`, keyed by its text) is reused.
    A review that fails is a result ("error"), and the others go on."""
    reviewer = reviewer or rv_mod.review
    done = dict(done or {})

    def one(item):
        text = _proposal_text(item)
        if text in done:
            return done[text]
        try:
            r = reviewer(text, item.get("city") or city, client, letter_client, open_client, budget_usd=budget_usd)
        except Exception as e:  # noqa: BLE001: the program goes on without it
            if type(e).__name__ in ("BudgetExceeded", "ReplayMiss"):
                raise
            r = {"status": "error", "reason": f"{type(e).__name__}: {e}"[:300], "input": text}
        r = {**r, "program_text": text}
        if on_result:
            on_result(r)
        return r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, items))


def _avoided(appraisal: dict, fundable_only: bool = True) -> float | None:
    """Injury crashes a year the proposal is expected to avoid: its parts the review supports (or every estimated
    part), summed; None when no part is estimated."""
    parts = appraisal.get("parts") or [appraisal]
    vals = [(p.get("proposed") or {}).get("injury_crashes_avoided_per_year") for p in parts
            if not fundable_only or p.get("verdict") in FUNDABLE]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals), 2) if vals else None


def _alternative_gain(appraisal: dict) -> dict | None:
    alt = appraisal.get("best_alternative") or {}
    got = (appraisal.get("proposed") or {}).get("injury_crashes_avoided_per_year")
    if alt.get("injury_crashes_avoided_per_year") is None:
        return None
    return {"countermeasure": alt.get("countermeasure"), "injury_crashes_avoided_per_year":
            alt["injury_crashes_avoided_per_year"], "proposed_avoids": got}


def row(r: dict) -> dict:
    """One proposal's line in the program: what the review found, in numbers code can rank."""
    ap = r.get("appraisal") or {}
    prop = r.get("proposal") or {}
    cost = prop.get("cost_usd") if prop.get("cost_usd") else None
    avoided = _avoided(ap) if ap else None
    out = {"input": r.get("program_text") or r.get("input"), "status": r.get("status"), "corner": r.get("corner"),
           "verdict": r.get("verdict"), "verdict_text": r.get("verdict_text"),
           "parts": [{"countermeasure": p.get("countermeasure"), "verdict": p.get("verdict")}
                     for p in ap.get("parts") or []],
           "cost_usd": cost, "cost_covers": prop.get("cost_covers"),
           "injury_crashes_avoided_per_year": avoided,
           "per_million_usd": round(avoided / (cost / 1e6), 2) if avoided and cost else None,
           "reasons": ap.get("reasons") or [], "alternative": _alternative_gain(ap) if r.get("verdict") ==
           "compare_alternative" else None,
           "objections_kept": len(r.get("objections") or []),
           "memo": r.get("saved"), "reason": r.get("reason"),
           "cost_of_review_usd": round(sum(float(v or 0) for v in (r.get("cost_usd") or {}).values()), 4)}
    return out


def rank(results: list[dict], budget_usd: float | None = None) -> dict:
    """The program: every proposal in its group, the supported ones ranked by injury crashes avoided per dollar
    (where a cost is known) and then per year; with a budget, the supported projects that fit, best value first."""
    rows = [row(r) for r in results]
    groups = {g: [] for g, _, _ in GROUPS}
    not_reviewed = []
    for x in rows:
        g = next((g for g, _, vs in GROUPS if x["verdict"] in vs), None)
        if x["status"] != "published" or g is None:
            not_reviewed.append(x)
        else:
            groups[g].append(x)
    # the proposal's own text breaks ties, so the order never depends on which review finished first (T29)
    key = lambda x: (-(x["per_million_usd"] or -1), -(x["injury_crashes_avoided_per_year"] or 0), x["input"] or "")
    for g in groups:
        groups[g].sort(key=key)
    fundable = groups["build"] + groups["site_check"] + [x for x in groups["parts"] if x["injury_crashes_avoided_per_year"]]
    plan = None
    if budget_usd:
        costed = sorted([x for x in fundable if x["cost_usd"]], key=key)
        chosen, left = [], budget_usd
        for x in costed:
            if x["cost_usd"] <= left:
                chosen.append(x["input"])
                left -= x["cost_usd"]
        plan = {"budget_usd": budget_usd, "chosen": chosen, "spent_usd": round(budget_usd - left),
                "left_usd": round(left), "avoided_per_year": round(sum(x["injury_crashes_avoided_per_year"] or 0
                                                                       for x in costed if x["input"] in chosen), 2),
                "no_cost_given": [x["input"] for x in fundable if not x["cost_usd"]]}
    totals = {"proposals": len(rows), "reviewed": len(rows) - len(not_reviewed),
              **{g: len(v) for g, v in groups.items()}, "not_reviewed": len(not_reviewed),
              "avoided_per_year_if_supported_built": round(sum(x["injury_crashes_avoided_per_year"] or 0
                                                               for x in fundable), 2),
              "reconsider_cost_usd": round(sum(x["cost_usd"] or 0 for x in groups["reconsider"])) or None,
              "review_cost_usd": round(sum(x["cost_of_review_usd"] for x in rows), 2)}
    return {"totals": totals, "groups": groups, "not_reviewed": not_reviewed, "budget_plan": plan}


def _money(v) -> str:
    return f"${v:,.0f}" if v else "not given"


def portfolio_md(p: dict, title: str = "Program review") -> str:
    t = p["totals"]
    L = [f"# {title}", "",
         f"{t['proposals']} proposals; {t['reviewed']} reviewed, each against its own corner's crash record, by the "
         "Before you commit review (Muse Spark investigates, code sets each verdict, Muse Spark Open argues against "
         "it). Code ranks the list; no model compares one corner with another.", "",
         "| Group | Proposals |", "|---|---|"]
    L += [f"| {label} | {t[g]} |" for g, label, _ in GROUPS] + [f"| Not reviewed | {t['not_reviewed']} |", ""]
    if t["avoided_per_year_if_supported_built"]:
        L += [f"If every supported project is built, the reviews expect about "
              f"{t['avoided_per_year_if_supported_built']} injury crashes avoided a year (national and local "
              "evidence, the corner's own record; each memo gives its range and conditions).", ""]
    if t.get("reconsider_cost_usd"):
        L += [f"Projects to reconsider carry {_money(t['reconsider_cost_usd'])} of stated cost.", ""]
    plan = p.get("budget_plan")
    if plan:
        L += [f"## Within a budget of {_money(plan['budget_usd'])}", "",
              f"Best value first (injury crashes avoided per dollar): {len(plan['chosen'])} project(s), "
              f"{_money(plan['spent_usd'])}, about {plan['avoided_per_year']} injury crashes avoided a year; "
              f"{_money(plan['left_usd'])} left."]
        L += [f"- {x}" for x in plan["chosen"]]
        if plan["no_cost_given"]:
            L += ["", "Supported but no cost given (add one to rank them):"] + [f"- {x}" for x in plan["no_cost_given"]]
        L.append("")
    for g, label, _ in GROUPS:
        if not p["groups"][g]:
            continue
        L += [f"## {label}", "", "| Proposal | Corner | Avoided a year | Cost | Per $1M | Why |", "|---|---|---|---|---|---|"]
        for x in p["groups"][g]:
            why = "; ".join(x["reasons"])[:220]
            if x.get("alternative"):
                a = x["alternative"]
                why += f" (alternative: {a['countermeasure']}, {a['injury_crashes_avoided_per_year']} a year)"
            L.append(f"| {x['input'][:110]} | {x['corner'] or ''} | {x['injury_crashes_avoided_per_year'] if x['injury_crashes_avoided_per_year'] is not None else '-'} "
                     f"| {_money(x['cost_usd'])} | {x['per_million_usd'] if x['per_million_usd'] is not None else '-'} | {why} |")
        L.append("")
    if p["not_reviewed"]:
        L += ["## Not reviewed", ""] + [f"- {x['input'][:140]}: {x.get('reason') or x.get('status')}" for x in p["not_reviewed"]] + [""]
    L += [f"Cost of the reviews: ${t['review_cost_usd']} (Meta API and open weights). Each proposal's memo, with its "
          "receipts and the red team's checked objections, is saved beside this file.", ""]
    return "\n".join(L)


def run(text: str, city: str, client=None, letter_client=None, open_client=None, budget_usd: float | None = None,
        per_review_usd: float = 0.50, out_dir: Path | None = None, title: str | None = None, reviewer=None,
        workers: int = WORKERS) -> dict:
    """Review a program list and save program.json and program.md, resuming any proposals already reviewed in
    out_dir (so an interrupted program never pays twice)."""
    items = read_list(text)
    if not items:
        raise ValueError("no proposals in the list: give one per line, a CSV with a 'text' column, or a JSON list")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out_dir or Path(SETTINGS.runs_dir) / "programs" / f"{stamp}_{city}")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "reviews.jsonl"
    done = {}
    if log.exists():
        for line in log.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") in ("published", "abstained"):
                done[r["program_text"]] = r
    import threading
    lock = threading.Lock()

    def keep(r):
        with lock:
            with log.open("a") as f:
                f.write(json.dumps(r, default=str) + "\n")

    t0 = time.time()
    results = review_all(items, city, client, letter_client, open_client, per_review_usd, workers, done,
                         reviewer, keep)
    p = rank(results, budget_usd)
    p.update({"city": city, "title": title or f"Program review: {len(items)} proposals",
              "seconds": round(time.time() - t0, 1)})
    (out_dir / "program.json").write_text(portable(json.dumps(p, indent=1, default=str)))
    (out_dir / "program.md").write_text(portable(portfolio_md(p, p["title"])))
    p["out_dir"] = str(out_dir)
    return p


def run_registered(spec_id: str, client, open_client, reviewer=None) -> dict:
    """A registered program run (validation/experiments/T29*.json): every program list it names, reviewed and
    ranked, resumed from the saved reviews of an interrupted run."""
    import os
    from .evaluate import RESULTS_DIR
    from .orchestrator import redact
    sp = json.loads((Path(__file__).resolve().parent.parent / "validation" / "experiments" / f"{spec_id}.json").read_text())
    os.environ["NML_ASOF"] = sp["asof"]
    data = json.loads(EXAMPLES.read_text())
    progs = [p for p in data["programs"] if p["id"] in sp["programs"]]
    out = []
    for prog in progs:
        p = run(json.dumps(prog["projects"]), prog["city"], client, None, open_client,
                budget_usd=prog.get("budget_total_usd"), per_review_usd=sp["budget_usd"], title=prog["title"],
                out_dir=Path(SETTINGS.runs_dir) / "programs" / f"{spec_id}_{prog['id']}", reviewer=reviewer)
        reviews = [json.loads(x) for x in (Path(p["out_dir"]) / "reviews.jsonl").read_text().splitlines()]
        latest = {}
        for r in reviews:  # an interrupted program's retried review replaces its failed one
            latest[r["program_text"]] = r
        out.append({"id": prog["id"], "city": prog["city"], "agency": prog.get("agency"), "title": prog["title"],
                    "source": prog["source"], "program": {k: p[k] for k in ("totals", "groups", "not_reviewed",
                                                                            "budget_plan", "seconds")},
                    "reviews": list(latest.values())})
        print(prog["id"], json.dumps(p["totals"]), flush=True)
    res = {"id": spec_id, "programs": out}
    path = RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"
    path.write_text(redact(portable(json.dumps(res, indent=1, default=str))))
    return res


def run_summary(res: dict, spec: dict) -> dict:
    """The registered rule, measured: how many proposals were reviewed, on their own corner, at what cost, and
    whether code's ranking is reproduced exactly from the saved reviews."""
    reviews = [r for p in res["programs"] for r in p["reviews"]]
    pub = [r for r in reviews if r.get("status") == "published"]
    on_corner = [r for r in pub if rv_mod.same_corner((r.get("proposal") or {}).get("address") or r.get("input", ""),
                                                      r.get("corner") or "")]
    usd = [sum(float(v or 0) for v in (r.get("cost_usd") or {}).values()) for r in reviews]
    again = [rank(p["reviews"], (p["program"].get("budget_plan") or {}).get("budget_usd")) for p in res["programs"]]
    same = all(json.dumps(a["totals"], sort_keys=True) == json.dumps(p["program"]["totals"], sort_keys=True)
               and json.dumps(a["groups"], sort_keys=True, default=str) == json.dumps(p["program"]["groups"], sort_keys=True, default=str)
               for a, p in zip(again, res["programs"]))
    rule = spec["rule"]
    out = {"programs": len(res["programs"]), "proposals": len(reviews), "reviewed": len(pub),
           "on_proposed_corner": len(on_corner),
           "groups": {g: sum(p["program"]["totals"][g] for p in res["programs"]) for g, _, _ in GROUPS},
           "abstained_or_failed": len(reviews) - len(pub),
           "ranking_reproduced": same,
           "objections_kept": sum(len(r.get("objections") or []) for r in pub),
           "mean_usd": round(sum(usd) / len(usd), 4) if usd else None, "total_usd": round(sum(usd), 4)}
    met = {"reviewed": len(pub) >= rule["min_reviewed_share"] * len(reviews),
           "on_proposed_corner": len(on_corner) == len(pub),
           "ranking_reproduced": same,
           "cost": out["mean_usd"] is not None and out["mean_usd"] <= rule["max_mean_usd"]}
    out["met"], out["rule_met"] = met, all(met.values())
    return out
