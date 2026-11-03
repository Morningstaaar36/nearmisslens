"""Program intake: an agency's own pages (a Safe Routes to School list, a board agenda, a contract's location list, a
notice of intent) read by Muse Spark into a list of proposed intersection projects, ready for program review.

Muse Spark reads the pages and lists every project at one intersection, with the sentence it rests on. Code keeps a
project only when that sentence is on the page word for word and names both of its streets, and a cost only when the
sentence states it; everything refused is listed with why. A page that refuses automated readers is reported as
unreadable, never fetched another way; its list can be pasted or saved to a file instead.

    nml intake URL [URL ...] --city CITY            # the list, to read and edit before reviewing it
    nml portfolio --from-url URL [URL ...] --city CITY   # read the pages, then review and rank every project"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from . import orchestrator
from .agent import Tool, run_agent
from .brief import same_corner

MAX_PAGE_CHARS = 150_000  # T30: a 41,700-character page cut at 40,000 lost its last projects
MAX_OUTPUT_TOKENS = 32_000
STATUS = ("planned or proposed", "completed", "not stated")

INSTRUCTIONS = """You read pages a street-safety agency published and list the projects on them that are each at ONE
intersection (two or three named streets that meet). For each project give:
- page: the page id it is on;
- intersection: "Street A & Street B" (or "Street A & Street B & Street C" where three streets meet), the street
  names as the page writes them;
- treatment: what will be built or changed there, in plain words (e.g. "rapid flashing beacons and curb ramps");
- status: "planned or proposed", "completed" or "not stated", as the page says;
- cost_usd: only if the page states a cost for this project alone or for the package it belongs to, else null;
  cost_covers: "this fix only", "a package with other work" or "not stated";
- source_says: ONE passage copied exactly from the page (at most about 300 characters) that names both streets;
- treatment_says: when source_says does not say what will be done there (a page that lists locations under one
  description, e.g. "Project Locations: A St & B Ave, C St & D Ave"), the passage copied exactly from the page that
  says what will be done at the listed locations; otherwise null.
List every project: long pages often hold dozens, and the last ones count as much as the first.
Leave out corridor-wide projects with no single intersection, and anything outside the city named in the task.
Code checks every project: the passage must be on the page word for word and name both streets, and a cost must be in
the passage. Submit every project in one submit_projects call; you will be told which were refused and why, and may
submit corrections once."""


def read_pages(sources: list[str]) -> tuple[dict[str, str], list[str]]:
    """Each source's text: a URL read as the citation gate reads it, or a local file (text or HTML). Returns
    ({id: text}, [ids that could not be read])."""
    pages, unreadable = {}, []
    for s in sources:
        p = Path(s)
        if not re.match(r"https?://", s) and p.exists():
            raw = p.read_text(errors="ignore")
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(
                r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I))))
            pages[f"file:{p.name}"] = text
            continue
        text = orchestrator.text_of(s)
        if text:
            pages[s] = text
        else:
            unreadable.append(s)
    return pages, unreadable


def check_project(x: dict, pages: dict[str, str]) -> str | None:
    """Why a submitted project is refused, or None to keep it."""
    page = x.get("page")
    if page not in pages:
        return f"no page {page!r}; use one of the page ids given"
    said = str(x.get("source_says") or "")
    if orchestrator.quote_check(said, page, pages) != "verified":
        return "source_says is not on the page word for word"
    streets = [s.strip() for s in str(x.get("intersection") or "").split("&") if s.strip()]
    if len(streets) not in (2, 3):  # round 3: three-street junctions were silently left out
        return "intersection must be two or three streets joined by '&'"
    missing = [s for s in streets if not orchestrator.names_corner(said, s)]
    if missing:
        return f"source_says does not name {', '.join(missing)}"
    if not str(x.get("treatment") or "").strip():
        return "no treatment"
    if x.get("treatment_says") and orchestrator.quote_check(str(x["treatment_says"]), page, pages) != "verified":
        return "treatment_says is not on the page word for word"
    return None


def cost_stated(x: dict) -> bool:
    """Whether the passage states the project's cost as given (with or without thousands commas)."""
    if not x.get("cost_usd"):
        return False
    n = f"{float(x['cost_usd']):,.0f}"
    said = str(x.get("source_says") or "").replace(" ", "")
    return any(c in said for c in (n, n.replace(",", "")))


def proposal_text(x: dict) -> str:
    """The project as a proposal for nml review: the treatment, the intersection, and the cost when stated."""
    t = f"{x['treatment'][:1].upper()}{x['treatment'][1:]} at {x['intersection']}"
    if x.get("cost_usd"):
        t += f", ${float(x['cost_usd']):,.0f} ({x.get('cost_covers') or 'not stated'})"
    return t


def extract(sources: list[str], city_name: str, client, budget_usd: float = 0.20, include_completed: bool = False,
            pages: dict | None = None) -> dict:
    """Read the pages and return {"projects", "refused", "unreadable", "usd", "pages"}; projects carry "text", the
    proposal for nml review."""
    got, unreadable = (pages, []) if pages is not None else read_pages(sources)
    if not got:
        return {"projects": [], "refused": [], "unreadable": unreadable, "usd": 0.0, "pages": []}
    kept, refused, rounds = [], [], []

    def submit_projects(projects: list[dict]):
        rounds.append(1)
        if len(rounds) > 2:
            return {"error": "submitted twice already: stop"}
        bad = []
        for x in projects:
            why = check_project(x, got)
            dup = any(same_corner(x.get("intersection", ""), k["intersection"]) and
                      same_corner(k["intersection"], x.get("intersection", "")) and k["page"] == x.get("page")
                      for k in kept)
            if why is None and dup:
                continue  # submitted again with the corrections: already kept
            if why:
                bad.append({**{k: x.get(k) for k in ("page", "intersection", "treatment")}, "why": why})
                continue
            row = {k: x.get(k) for k in ("page", "intersection", "treatment", "status", "cost_usd", "cost_covers",
                                         "source_says", "treatment_says")}
            if row["cost_usd"] and not cost_stated(row):  # a cost the passage does not state is dropped, not guessed
                row.update(cost_usd=None, cost_covers="not stated", cost_dropped=True)
            kept.append(row)
        refused[:] = [r for r in refused if not any(r["intersection"] == k["intersection"] for k in kept)] + bad
        if bad and len(rounds) == 1:
            return {"error": f"{len(bad)} refused; correct them (copy the passage exactly; it must name both streets) "
                             "or leave them out", "refused": bad[:20], "kept": len(kept)}
        return {"ok": True, "kept": len(kept), "refused": len(bad)}

    item = {"type": "object", "properties": {
        "page": {"type": "string"}, "intersection": {"type": "string"}, "treatment": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUS)}, "cost_usd": {"type": ["number", "null"]},
        "cost_covers": {"type": "string", "enum": ["this fix only", "a package with other work", "not stated"]},
        "source_says": {"type": "string"}, "treatment_says": {"type": ["string", "null"]}},
        "required": ["page", "intersection", "treatment", "status", "cost_usd", "cost_covers", "source_says",
                     "treatment_says"],
        "additionalProperties": False}
    tool = Tool("submit_projects", "Submit every single-intersection project on the pages.",
                {"type": "object", "properties": {"projects": {"type": "array", "items": item}},
                 "required": ["projects"], "additionalProperties": False}, submit_projects)
    task = json.dumps({"city": city_name, "pages": [{"id": k, "text": v[:MAX_PAGE_CHARS]} for k, v in got.items()]})
    run = run_agent(client, orchestrator.MODEL, INSTRUCTIONS, task, [tool], 4, budget_usd, effort="low",
                    tag=f"intake {city_name}", required=("submit_projects",),
                    max_output_tokens=MAX_OUTPUT_TOKENS)  # T30b: a page of 20+ projects passed 8,000 tokens
    projects = [{**x, "text": proposal_text(x)} for x in kept
                if include_completed or x.get("status") != "completed"]
    return {"projects": projects, "completed_left_out": sum(x.get("status") == "completed" for x in kept)
            if not include_completed else 0,
            "refused": refused, "unreadable": unreadable, "usd": round(run.usd, 4), "pages": list(got)}


def hand_corner(text: str) -> str:
    """The intersection a hand-written project sentence names: the capitalized or numbered words on each side of
    its "&" ("... curb bulbs at NW 65th St & 3rd Ave NW (Safe Routes ..." -> "NW 65th St & 3rd Ave NW")."""
    left, _, right = text.partition(" & ")
    word = r"(?:[A-Z0-9][\w.'-]*)"
    a = re.search(rf"((?:{word} )*{word})$", left)
    b = re.match(rf"((?:{word} )*{word})", right)
    return f"{a.group(1) if a else left} & {b.group(1) if b else right}"


def run_registered(spec_id: str, client) -> dict:
    """A registered intake run (validation/experiments/T30.json): each page read, every project kept with its status,
    scored against the hand-collected lists in validation/examples/programs.json."""
    from .config import ROOT, portable
    from .evaluate import RESULTS_DIR
    from . import opendata
    sp = json.loads((ROOT / "validation" / "experiments" / f"{spec_id}.json").read_text())
    path = RESULTS_DIR / "bench" / f"experiment_{spec_id}.json"
    done = {r["id"]: r for r in (json.loads(path.read_text())["inputs"] if path.exists() else [])}
    out = []
    for inp in sp["inputs"]:
        if inp["id"] in done:
            out.append(done[inp["id"]])
            continue
        r = extract([inp["url"]], opendata.city(inp["city"])["name"], client, include_completed=True)
        out.append({**inp, **r})
        print(inp["id"], len(r["projects"]), "kept;", len(r["refused"]), "refused;", r["unreadable"], r["usd"], flush=True)
        path.write_text(orchestrator.redact(portable(json.dumps({"id": spec_id, "inputs": out}, indent=1))))
    return {"id": spec_id, "inputs": out}


def run_summary(res: dict, spec: dict) -> dict:
    """The registered rule, measured: recall of the hand-collected projects, the controls, the cost."""
    from .config import ROOT
    programs = {p["id"]: p for p in json.loads((ROOT / "validation" / "examples" / "programs.json").read_text())["programs"]}
    rows, found, wanted = [], 0, 0
    for r in res["inputs"]:
        hand = programs[r["program"]]["projects"] if r.get("program") else []
        names = [hand_corner(h["text"]) for h in hand]
        hits = [n for n in names if any(same_corner(n, x["intersection"]) and same_corner(x["intersection"], n)
                                        for x in r["projects"])]
        found, wanted = found + len(hits), wanted + len(names)
        rows.append({"id": r["id"], "kept": len(r["projects"]), "refused": len(r["refused"]),
                     "planned": sum(x.get("status") == "planned or proposed" for x in r["projects"]),
                     "completed": sum(x.get("status") == "completed" for x in r["projects"]),
                     "hand_list": len(names), "hand_found": len(hits),
                     "missed": [n for n in names if n not in hits], "unreadable": bool(r["unreadable"]),
                     "usd": r["usd"]})
    readable = [x for x in rows if not x["unreadable"] and x["hand_list"]]
    controls = [x for x in rows if not x["hand_list"]]
    out = {"pages": len(rows), "hand_projects": wanted, "hand_found": found,
           "recall": round(found / wanted, 3) if wanted else None,
           "controls_empty": all(x["kept"] == 0 for x in controls),
           "mean_usd_per_readable_page": round(sum(x["usd"] for x in readable) / len(readable), 4) if readable else None,
           "rows": rows}
    rule = spec["rule"]
    out["met"] = {"recall": out["recall"] is not None and out["recall"] >= rule["min_recall"],
                  "controls_empty": out["controls_empty"],
                  "cost": out["mean_usd_per_readable_page"] is not None
                  and out["mean_usd_per_readable_page"] <= rule["max_usd_per_page"]}
    out["rule_met"] = all(out["met"].values())
    return out
