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

from . import citywide, engineer, opendata
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
          letter_client=None, workers: int = 3, saved_only: bool = False) -> dict:
    city = city or next(iter(citywide.cities()), None)  # the first city with a saved screen
    if not city:
        raise ValueError("no city has a saved screen yet; run nml citywide --city CITY")
    src = SETTINGS.runs_dir / "engineer" / city
    # reuses saved reports and builds any that are missing (saved_only: a preview from what is already built)
    index = engineer.precompute(city, letters=letters, letter_client=letter_client, out_dir=src, workers=workers,
                                saved_only=saved_only)
    root = docs / "data"
    data = root / city
    asks = answered(city)
    for sub in ("j", "media"):
        if (data / sub).exists():
            shutil.rmtree(data / sub)
    (data / "j").mkdir(parents=True)
    for k, row in enumerate(index):
        path = src / f"{row['slug']}.json"
        full = engineer.refresh(json.loads(path.read_text()))
        path.write_text(json.dumps(full, indent=0, default=str))  # the saved report matches what the site shows
        rep = compact(full)
        rep["asks"] = asks.get(row["slug"], [])
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
    screen = dict(citywide.screened()).get(city, {})
    c = opendata.city(city) or {}
    (data / "index.json").write_text(json.dumps({"city": city, "city_name": c.get("name", city), "bbox": c.get("bbox"),
                                                 "asof": asof().isoformat(), "summary": screen.get("summary", {}),
                                                 "screen": "priority list" if citywide.junction_adapters(city) else "crash clusters",
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


def check(docs: Path = DOCS) -> list[str]:
    """No machine paths and nothing that looks like a key in anything the site publishes."""
    out = []
    for p in [docs / "index.html", docs / "copilot.js", *(docs / "data").rglob("*.json")]:
        if not p.exists() or "video" in p.parts:
            continue
        text = p.read_text()
        if "/home/" in text or "/Users/" in text:
            out.append(f"{p.relative_to(docs)} contains a machine path")
        if '"True"' in text or '"False"' in text:
            out.append(f"{p.relative_to(docs)} holds a true/false value saved as text")
        if SECRETISH.search(text):
            out.append(f"{p.relative_to(docs)} contains something that looks like a key")
    return out
