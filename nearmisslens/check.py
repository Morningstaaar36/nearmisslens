"""Check a claim: one entry for every front end (CLI, web job, tests).

Give it a real input and a city from the registry:
- a URL (a news story, an official statement): the desk reads it first;
- a claim in your own words: the desk finds a published source for it with web search;
- a source's own text (--as-source): the text itself is the source, cited as `input:text`;
- a resident's report, with an optional photo URL and address.

The desk (orchestrator.run_case) does the work behind the same gates as the registered runs; this module only builds
the task from a generic template and the registry's city name, refuses a city the registry cannot serve, and writes
the result as JSON and a readable Markdown report. Nothing here knows any particular city, corner or source."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from . import opendata, orchestrator
from .config import SETTINGS, portable

KINDS = ("url", "find", "source", "report")
MAX_INPUT = 2000
SOURCE_ID = "input:text"


def supported(city: str | None) -> tuple[dict | None, str | None]:
    """The registry city, or None and why it cannot be checked here (no such city, or no crash data)."""
    c = opendata.city(city)
    if c is None:
        known = ", ".join(x["id"] for x in opendata.load_cities())
        return None, f"{city!r} is not a city in the registry ({known}); add it with nml add-city, then nml discover"
    if "crash" not in opendata.coverage(c["id"])["kinds"]:
        return None, (f"{c['name']} has no crash data registered, so nothing can be checked against its record; "
                      "run nml discover LAT LON for a point in the city")
    return c, None


def kind_of(text: str, kind: str | None = None) -> str:
    if kind:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return kind
    return "url" if re.match(r"https?://", text.strip()) else "find"


def task_for(text: str, city_name: str, kind: str, photo: str | None = None, address: str | None = None) -> str:
    """The desk's task, from a generic template and the city's registry name only."""
    tail = ("investigate the intersection it names, check what it says against the city's record, and draft the "
            "request letter.")
    if kind == "url":
        return f"Read this source about street safety in {city_name}: {text.strip()} . Read it with read_page, {tail}"
    if kind == "find":
        return (f"Find a published source (news report, official statement or report) for this claim about street "
                f"safety in {city_name}: \"{text.strip()}\". Read it with read_page, {tail}")
    if kind == "source":
        return (f"The source is the text handed to you as {SOURCE_ID} (read it with read_page on that id and cite it "
                f"by that id). It is about street safety in {city_name}. {tail[0].upper()}{tail[1:]}")
    where = f" at {address.strip()}, {city_name}" if address else f" in {city_name}"
    pic = f"; photo: {photo.strip()}. Look at the photo" if photo else ". There is no photo"
    return (f"A resident reports{where}: \"{text.strip()}\"{pic}, investigate the nearest intersection, say how urgent "
            "this is given the crash record there, and draft the work order to the agency that owns the road.")


def validate(text: str, city: str, kind: str | None = None, photo: str | None = None) -> tuple[str, dict]:
    """The input's kind and the registry city, or ValueError with a plain reason."""
    if not text or not text.strip():
        raise ValueError("give a URL, a claim or a report to check")
    if len(text) > MAX_INPUT:
        raise ValueError(f"the input is longer than {MAX_INPUT} characters")
    k = kind_of(text, kind)
    if k == "url" and not orchestrator.public_url(text.strip()):
        raise ValueError("only public http(s) pages can be read")
    if photo and not orchestrator.public_url(photo.strip()):
        raise ValueError("the photo must be a public http(s) URL")
    c, why = supported(city)
    if c is None:
        raise LookupError(why)
    return k, c


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "case"


def check(text: str, city: str, kind: str | None = None, photo: str | None = None, address: str | None = None,
          letter: bool = True, budget_usd: float = 0.50, max_turns: int = 22, client=None, letter_client=None,
          model_check_client=None, out_dir: Path | None = None, runner=None) -> dict:
    """Run the desk on one input and save the result. `runner` stands in for orchestrator.run_case in tests."""
    t0 = time.time()
    try:
        k, c = validate(text, city, kind, photo)
    except LookupError as e:
        return {"status": "unsupported_city", "reason": str(e), "city": city, "input": text}
    pages = {SOURCE_ID: text.strip()} if k == "source" else None
    task = task_for(text, c["name"], k, photo, address)
    run = runner or orchestrator.run_case
    try:
        r = run(task, c["id"], client, letter_client=letter_client if letter else None,
                model_check_client=model_check_client, budget_usd=budget_usd, max_turns=max_turns, pages=pages)
    except Exception as e:  # a failed run is reported as an error, never as a published case
        return {"status": "error", "reason": f"{type(e).__name__}: {e}", "city": c["id"], "input": text, "kind": k,
                "seconds": round(time.time() - t0, 1)}
    final = r.get("final") or {}
    claims = [{"id": rid, **v["data"]} for rid, v in (r.get("receipts") or {}).items()
              if v.get("tool") == "check_claim" and isinstance(v.get("data"), dict)]
    last = (r.get("trace") or [{}])[-1]
    out = {"status": "published" if r.get("finished") else "abstained",
           "reason": None if r.get("finished") else
           f"not published ({r.get('stopped')}): " + "; ".join(last.get("errors") or [last.get("error") or ""]).strip("; "),
           "city": c["id"], "city_name": c["name"], "kind": k, "input": orchestrator.redact(text), "task": task,
           "corner": r.get("corner"), "summary": orchestrator.redact(final.get("summary") or ""),
           "findings": [{**f, "text": orchestrator.redact(f.get("text", ""))} for f in final.get("findings") or []],
           "sources": final.get("sources") or [], "claims": claims,
           "letter": orchestrator.redact(r.get("letter") or "") or None,
           "receipts": r.get("receipts"), "cost_usd": {"meta": r.get("usd")}, "turns": r.get("turns"),
           "seconds": round(time.time() - t0, 1), "asof": r.get("asof"), "source": "live" if not SETTINGS.replay else "replay"}
    save(out, out_dir)
    return out


def save(out: dict, out_dir: Path | None = None) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    d = out_dir or SETTINGS.runs_dir / "checks" / f"{stamp}_{_slug(out.get('corner') or out.get('input') or '')}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(portable(json.dumps(out, indent=1, default=str)))
    (d / "report.md").write_text(report_md(out))
    out["saved"] = portable(str(d))
    return d


def report_md(r: dict) -> str:
    """The result as a readable report: verdicts, findings with their receipts, sources with their quote check."""
    L = [f"# {r.get('corner') or 'No corner'}: {r['status']}", "",
         f"- **City:** {r.get('city_name') or r.get('city')}  ",
         f"- **Input ({r.get('kind')}):** {r.get('input')}  ",
         f"- **Records as of:** {r.get('asof')}  ",
         f"- **Cost:** ${(r.get('cost_usd') or {}).get('meta')} Meta API, {r.get('turns')} turns, {r.get('seconds')} s", ""]
    if r.get("reason"):
        L += [f"**Why:** {r['reason']}", ""]
    if r.get("summary"):
        L += [r["summary"], ""]
    if r.get("claims"):
        L += ["## Claims checked against the record", "", "| claim | verdict | record frame |", "|---|---|---|"]
        L += [f"| {c.get('claim', '').replace('|', '/')} | {c.get('verdict')} | {(c.get('frame') or '').replace('|', '/')} |"
              for c in r["claims"]]
        L.append("")
    if r.get("findings"):
        L += ["## Findings", ""] + [f"- {f.get('text')} [{f.get('receipt')}]" for f in r["findings"]] + [""]
    if r.get("sources"):
        L += ["## Sources", ""] + [f"- {s.get('url')} ({s.get('quote_check', 'unchecked')}): \"{s.get('quote')}\""
                                   for s in r["sources"]] + [""]
    if r.get("letter"):
        L += ["## Draft letter (review it; NearMissLens sends nothing)", "", r["letter"], ""]
    return "\n".join(L)


def cities() -> list[dict]:
    """Each registry city and what it supports here, for `nml cities` and the web's city list."""
    out = []
    for c in opendata.load_cities():
        cov = opendata.coverage(c["id"])
        out.append({"id": c["id"], "name": c["name"], "checkable": "crash" in cov["kinds"],
                    "has": sorted(cov["kinds"]), "missing": cov["missing"]})
    return out
