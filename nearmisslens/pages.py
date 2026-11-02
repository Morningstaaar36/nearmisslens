"""The static copilot for GitHub Pages (nml pages): the same page as the live app, reading precomputed engineer reports.

    docs/index.html, copilot.js, copilot.css      the page (nearmisslens/web/), mode "static"
    docs/data/index.json                          the cities built so far and the default one
    docs/data/<city>/index.json                   the city's screened corners, worst first, and its summary
    docs/data/<city>/j/<slug>.json                one engineer report per corner (engineer.precompute)
    docs/data/<city>/media/<slug>/aerial.jpg      the aerial photo, for the first corners
    docs/data/evidence.json                       what the causal gate found for every tested program

Nothing here needs a key: the reports are deterministic, and letters appear only where one was drafted and checked.
A live endpoint (the Modal app) can be named with --live; the page then sends other addresses to it."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import citywide, context, engineer, opendata
from .config import ROOT, SETTINGS, asof

WEB = Path(__file__).resolve().parent / "web"
DOCS = ROOT / "docs"
SECRETISH = re.compile(r"(sk-[A-Za-z0-9]{16,}|api[_-]?key\"?\s*[:=]\s*\"[^\"]{8,}|Bearer\s+[A-Za-z0-9._-]{16,})", re.I)


def page(mode: str, live: str = "") -> str:
    if live and not live.startswith("https://"):
        raise ValueError("the live endpoint must be an https:// URL")
    return (WEB / "copilot.html").read_text().replace("__MODE__", mode).replace("__LIVE__", live)


def compact(rep: dict) -> dict:
    """The report without what the page never shows (full crash rows, long pattern tails, the dossier's raw lists)."""
    f = dict(rep["findings"])
    fx = dict(f.get("choose_fixes") or {})
    cr = fx.get("crashes") or {}
    fx["crashes"] = {k: v for k, v in cr.items() if not isinstance(v, (list, dict)) or k in ("crash_groups",)}
    fx["options"] = (fx.get("options") or [])[:8]
    f["choose_fixes"] = fx
    rc = dict(f.get("root_cause") or {})
    # reports saved before rootcause returned plain bools hold "True"/"False" strings
    rc["patterns"] = [{**t, "over_represented": t.get("over_represented") in (True, "True")}
                      for t in (rc.get("patterns") or [])[:12]]
    rc["over_represented"] = [t for t in rc["patterns"] if t["over_represented"]]
    f["root_cause"] = rc
    f.pop("screen_city", None)
    return {**{k: v for k, v in rep.items() if k != "findings"}, "findings": f}


def answered(city: str) -> dict[str, list[dict]]:
    """The checked answers from NML-Bench T17's gated arm, per corner, for the static page."""
    from .evaluate import RESULTS_DIR
    p = RESULTS_DIR / "bench" / "experiment_T17.json"
    if not p.exists():
        return {}
    res = json.loads(p.read_text())
    if res.get("spec", {}).get("city") != city:
        return {}
    out: dict[str, list[dict]] = {}
    for r in res.get("runs", []):
        if r["arm"] == "gated" and r.get("answer"):
            out.setdefault(r["corner"], []).append({"question": r["q"], "answer": r["answer"], "claims": r.get("claims") or [],
                                                    "refused": r.get("refused") or []})
    return out


def _brief_dir(name: str) -> Path:
    # brief.build's folder name for a junction
    return SETTINGS.runs_dir / "briefs" / "".join(ch if ch.isalnum() else "_" for ch in name.split(",")[0].lower())[:60]


def build(city: str | None = None, live: str = "", docs: Path = DOCS, media_top: int = 25, letters: int = 0,
          letter_client=None, workers: int = 3, saved_only: bool = False, model_check_client=None) -> dict:
    city = city or next(iter(citywide.cities()), None)  # the first city with a saved screen
    if not city:
        raise ValueError("no city has a saved screen yet; run nml citywide --city CITY")
    src = SETTINGS.runs_dir / "engineer" / city
    # reuses saved reports and builds any that are missing (saved_only: a preview from what is already built)
    index = engineer.precompute(city, letters=letters, letter_client=letter_client, out_dir=src, workers=workers,
                                saved_only=saved_only)
    seen, unique = set(), []
    for row in index:  # the city's list can name one point twice (two rows, one place): show it once
        key = (round(row["lat"], 5), round(row["lon"], 5))
        if key not in seen:
            seen.add(key)
            unique.append({**row, "rank": len(unique) + 1})
    index = unique
    root = docs / "data"
    data = root / city
    asks = answered(city)
    for sub in ("j", "media"):
        if (data / sub).exists():
            shutil.rmtree(data / sub)
    (data / "j").mkdir(parents=True)
    refreshed = []
    for k, row in enumerate(index):
        path = src / f"{row['slug']}.json"
        full = engineer.refresh(json.loads(path.read_text()))
        path.write_text(json.dumps(full, indent=0, default=str))  # the saved report matches what the site shows
        refreshed.append({**full, "_slug": row["slug"]})
        rep = compact(full)
        rep["asks"] = asks.get(row["slug"], [])
        ag = src.parent / "agent" / city / f"{row['slug']}.json"  # the agent's own case (nml agent-cases), if run
        if ag.exists():
            a = json.loads(ag.read_text())
            if a.get("finished"):
                keep, gone = engineer.recheck_agent(a, full, model_check_client)  # today's receipts, both gates
                rep["agent"] = {"summary": a.get("summary"), "claims": keep, "superseded": gone, "turns": a.get("turns"),
                                "usd": a.get("usd"), "refused": a.get("refused_attempts") or [],
                                "receipts": {r["id"]: r["tool"] for r in a.get("receipts") or []}}
        row["claim_errors"] = len(rep["claim_errors"])
        photo = _brief_dir(row["name"]) / "aerial.jpg"
        if not photo.exists():
            photo = SETTINGS.runs_dir / "site" / row["slug"] / "aerial.jpg"  # fetched by the site check
        if k < media_top and photo.exists():
            dst = data / "media" / row["slug"] / "aerial.jpg"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(photo, dst)
            rep["media"] = {"aerial": f"data/{city}/media/{row['slug']}/aerial.jpg"}
        (data / "j" / f"{row['slug']}.json").write_text(json.dumps(rep, separators=(",", ":"), default=str))
    # the city's action plan from the same refreshed cases: every number on the plan view and in its letters
    from . import plan as plan_
    pl = plan_.build(city, reports=refreshed)
    plan_.write(pl)
    (data / "plan.json").write_text(json.dumps(pl, separators=(",", ":"), default=str))
    (data / "plan.csv").write_text(plan_.to_csv(pl))
    screen = dict(citywide.screened()).get(city, {})
    c = opendata.city(city) or {}
    (data / "index.json").write_text(json.dumps({"city": city, "city_name": c.get("name", city), "bbox": c.get("bbox"),
                                                 "asof": asof().isoformat(), "summary": screen.get("summary", {}),
                                                 "screen": "priority list" if citywide.junction_adapters(city) else "crash clusters",
                                                 "plan": True, "years": context.YEARS,
                                                 "gap_min_injury_crashes": context.GAP_MIN_INJURY_CRASHES,
                                                 "corners": index}, indent=0))
    # the list of built cities (every docs/data/<city>/index.json); the first registry city with a list is the default
    built = []
    for f in sorted(root.glob("*/index.json")):
        ix = json.loads(f.read_text())
        built.append({"id": ix["city"], "name": ix["city_name"], "corners": len(ix["corners"]), "screen": ix.get("screen")})
    order = [c["id"] for c in opendata.load_cities()]
    built.sort(key=lambda b: (b["screen"] != "priority list", order.index(b["id"]) if b["id"] in order else 99))
    (root / "index.json").write_text(json.dumps({"cities": built, "default": built[0]["id"] if built else city}, indent=0))
    for legacy in ("j", "media"):  # the single-city layout before cities had folders
        if (root / legacy).exists():
            shutil.rmtree(root / legacy)
    from .app import evidence
    (root / "evidence.json").write_text(json.dumps(evidence(), indent=0, default=str))
    desk_page(root)
    (docs / "index.html").write_text(page("static", live))
    for name in ("copilot.js", "copilot.css"):
        shutil.copyfile(WEB / name, docs / name)
    (docs / ".nojekyll").write_text("")
    problems = check(docs)
    if problems:
        raise RuntimeError("the static site failed its checks: " + "; ".join(problems[:5]))
    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return {"corners": len(index), "letters": sum(r["letter"] for r in index), "mb": round(size / 1e6, 1),
            "claim_errors": sum(r["claim_errors"] for r in index),
            "path": str(docs.relative_to(ROOT)) if docs.is_relative_to(ROOT) else str(docs)}


def desk_page(root: Path) -> None:
    """The live desk for the site: the latest registered desk run's cases (T21c, else T21b, else T21), with every
    run's totals so earlier, weaker runs stay visible."""
    from .bench import desk_stats
    from .evaluate import RESULTS_DIR
    runs = [json.loads(p.read_text()) for p in (RESULTS_DIR / "bench" / f"experiment_{k}.json" for k in ("T21", "T21b", "T21c", "T21d"))
            if p.exists()]
    if not runs:
        return
    res = runs[-1]
    keep = ("kind", "city", "task", "finished", "stopped", "final", "corner", "letter", "usd", "seconds", "turns", "web",
            "trace", "receipts")
    from .orchestrator import redact
    cases = [{k: c.get(k) for k in keep} for c in res.get("cases", [])]
    review = {"checked": 0, "changed": 0}
    for c in cases:
        c["rechecks"] = rechecks(c)
        for f in (c.get("final") or {}).get("findings") or []:
            r = c["rechecks"].get(f.get("receipt"))
            if r:
                r["published"] = published_verdict(f.get("text", ""))
                review["checked"] += 1
                review["changed"] += r["published"] != r["verdict"]
    blob = redact(json.dumps({"run": res.get("id"), "runs": [desk_stats(r) for r in runs], "cases": cases,
                              "review": review}, default=str))
    (root / "desk.json").write_text(blob)  # no licence plate is published, even one a 311 report printed


def published_verdict(text: str) -> str | None:
    """The verdict a published finding states, read from its words ("contradicted" was the name before T21d)."""
    from .orchestrator import VERDICT_WORDS
    low = text.lower()
    if "contradict" in low:
        return "differs from the record"
    return next((v for v, ws in VERDICT_WORDS.items() if any(w in low for w in ws)), None)


def rechecks(case: dict) -> dict:
    """Each claim the case checked, verdict by the current claim check on the record the case read (rebuilt from the
    cache), keyed by the receipt the published finding cites, so a verdict our later fixes changed is shown changed."""
    from .orchestrator import Desk, _places, claim_verdict, replay_record
    steps = [s for s in case.get("trace") or [] if s.get("tool") == "check_claim" and not s.get("error")]
    rids = sorted((k for k, v in (case.get("receipts") or {}).items() if v.get("tool") == "check_claim"),
                  key=lambda k: int(k[1:]))
    try:
        rec = replay_record(case) if steps else {}
    except Exception:
        return {}
    places = _places(Desk(case.get("city")))
    places.places.add((case.get("corner") or "").split(",")[0])
    out = {}
    for rid, st in zip(rids, steps):
        tool = ((case.get("receipts") or {}).get(st["args"].get("receipt")) or {}).get("tool")
        if tool in rec:
            v, why, _ = claim_verdict(st["args"]["text"], rec[tool], places)
            out[rid] = {"claim": st["args"]["text"], "verdict": v, "reasons": why[:2]}
    return out


def check(docs: Path = DOCS) -> list[str]:
    """No machine paths and nothing that looks like a key in anything the site publishes."""
    out = []
    for p in [docs / "index.html", docs / "copilot.js", *(docs / "data").rglob("*.json")]:
        if not p.exists() or "video" in p.parts:
            continue
        text = p.read_text()
        local = re.sub(r"https?://[^\s\"'<>]+", "", text)  # a web address may contain /home/; a machine path may not
        if "/home/" in local or "/Users/" in local:
            out.append(f"{p.relative_to(docs)} contains a machine path")
        if '"True"' in text or '"False"' in text:
            out.append(f"{p.relative_to(docs)} holds a true/false value saved as text")
        if SECRETISH.search(text):
            out.append(f"{p.relative_to(docs)} contains something that looks like a key")
    return out
