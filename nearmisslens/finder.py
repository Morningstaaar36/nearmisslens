"""Find what an agency or the press has published, with Muse Spark and live web search.

    nml find CITY                         pages where the city's transportation agency lists planned intersection
                                          projects, then the projects read from them (ready for nml portfolio)
    nml find CITY --corner "A & B"        reports about one corner: agency pages, news, studies

Muse Spark 1.3 searches the web (the Meta API's web_search tool), opens pages and names each one with a passage
copied from it. Code then opens every page itself and keeps it only when it is a public page that loads, the passage
is on it word for word, and the page names the city (for a corner, both of its streets). Everything refused is
listed with why. The city's name and agency come from the registry, so nothing here knows any city, agency or site."""
from __future__ import annotations

import re

from . import opendata, orchestrator
from .agent import Tool, run_agent
from .config import asof

MAX_REPORTS = 5
MAX_AGE_YEARS = 3
MAX_READS = 6
MAX_SEARCHES = 6  # a live run (DC, 4 Nov 2026) made 19 searches and never submitted
READ_CHARS = 12_000  # of a page shown to the model; the gate checks the passage against the whole page
KINDS = ("project list", "agency page", "news", "study or plan", "other")

INSTRUCTIONS = """You find pages on the live web for a street-safety reviewer. Make at most {searches} web searches in
all, then open the most promising results with read_page (it reads PDFs too). After at most {reads} pages, submit what
you have, even if only one page fits. Return up to {n} pages, best first, in one submit_reports call:
- url: the page's address exactly as you opened it;
- title, publisher (who published it), published (the date the page states, or null);
- kind: one of {kinds};
- passage: ONE passage of 40 to 300 characters copied exactly from the text read_page returned (never from a search
  result's summary), that shows why it answers the task;
- what: one plain sentence on what the page proposes or reports.
Prefer the agency's own pages and documents from the last three years, then local news. Never invent a page or a
passage: code opens every page and refuses a passage that is not on it word for word, or a page that does not name
what the task names. You will be told what was refused and why, and may correct once."""

TASKS = {
    "projects": ("Find pages where {agency} lists several street-safety projects it plans or proposes, each at "
                 "one named intersection in {city}: a program's location list (new signals, beacons, crossings, "
                 "leading pedestrian intervals, Safe Routes to School), a council or commission agenda item, a notice. "
                 "A page about one corridor counts only if it names separate intersection treatments. The passage "
                 "must name an intersection."),
    "corner": ("Find published reports about the intersection of {corner} in {city}: the agency's project pages or "
               "studies, council items and local news about crashes or safety changes there. The passage must name "
               "the intersection's streets."),
}


def _mentions(text: str, name: str) -> bool:
    return f" {orchestrator._norm(name)} " in f" {orchestrator._norm(text)} "


def check_report(x: dict, city: dict, corner: str | None, seen: set[str], read: set[str] | None = None) -> str | None:
    """Why a submitted page is refused, or None to keep it."""
    url = str(x.get("url") or "")
    if url in seen:
        return "the same page twice"
    if not orchestrator.public_url(url):
        return "not a public web page"
    text = orchestrator.text_of(url)
    if text is None:
        return "the page could not be read here (it refuses automated readers or holds no text)"
    years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", str(x.get("published") or ""))]
    if years and max(years) < asof().year - MAX_AGE_YEARS:  # a 2019 release about signals already built (DC, live)
        return f"published in {max(years)}: look for pages from the last {MAX_AGE_YEARS} years"
    if orchestrator.quote_check(str(x.get("passage") or ""), url) != "verified":
        # code opens every page itself, so a page the model did not open still counts when its passage is on it
        return ("the passage is not on the page word for word" if read is None or url in read else
                "the passage is not on the page word for word: open it with read_page and copy from its text")
    agency = re.search(r"\(([^)]+)\)", city.get("agency") or "")
    if not (_mentions(text, city["name"]) or (agency and _mentions(text, agency.group(1)))):
        return f"the page does not name {city['name']}"
    if corner:
        streets = [s for s in re.split(r"\s*&\s*", corner.split(",")[0]) if s.strip()]
        missing = [s for s in streets if not orchestrator.names_corner(text, s)]
        if missing:
            return f"the page does not name {', '.join(missing)}"
    return None


def find(city_id: str, client, corner: str | None = None, budget_usd: float = 0.25) -> dict:
    """{"reports": [...], "refused": [...], "searches": [...], "usd"}: pages found by Muse Spark, each checked."""
    city = opendata.city(city_id)
    if city is None:
        raise LookupError(f"no registry city {city_id!r}")
    task = TASKS["corner" if corner else "projects"].format(
        agency=re.sub(r"^the\s+", "", city.get("agency") or f"{city['name']}'s transportation agency"),
        city=city["name"], corner=corner or "")
    kept, refused, reads, rounds, searches, opened = [], [], [], [], [], []

    def read_page(url: str) -> dict:
        reads.append(url)
        if len(reads) > MAX_READS:
            return {"error": f"read {MAX_READS} pages already: submit what you have"}
        text = orchestrator.text_of(url) if orchestrator.public_url(url) else None
        if text and url not in opened:
            opened.append(url)
        return {"text": text[:READ_CHARS], "pages_left": MAX_READS - len(reads)} if text else \
            {"error": "this page could not be read here; try another", "pages_left": MAX_READS - len(reads)}

    def submit_reports(reports: list[dict]) -> dict:
        rounds.append(1)
        if len(rounds) > 2:
            return {"error": "submitted twice already: stop"}
        bad = []
        for x in reports[:MAX_REPORTS]:
            why = check_report(x, city, corner, {k["url"] for k in kept}, opened)
            if why and any(k["url"] == x.get("url") for k in kept):
                continue  # resubmitted with the corrections: already kept
            row = {k: x.get(k) for k in ("url", "title", "publisher", "published", "kind", "passage", "what")}
            (bad.append({**row, "why": why}) if why else kept.append(row))
        refused[:] = [r for r in refused if r.get("url") not in {k["url"] for k in kept}] + bad
        if bad and len(rounds) == 1:
            return {"error": f"{len(bad)} refused; correct them or leave them out",
                    "refused": [{"url": b["url"], "why": b["why"]} for b in bad], "kept": len(kept)}
        return {"ok": True, "kept": len(kept)}

    item = {"type": "object", "properties": {
        "url": {"type": "string"}, "title": {"type": "string"}, "publisher": {"type": "string"},
        "published": {"type": ["string", "null"]}, "kind": {"type": "string", "enum": list(KINDS)},
        "passage": {"type": "string"}, "what": {"type": "string"}},
        "required": ["url", "title", "publisher", "published", "kind", "passage", "what"], "additionalProperties": False}
    tools = [Tool("read_page", "Open a web page and read its text.",
                  {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"],
                   "additionalProperties": False}, read_page),
             Tool("submit_reports", "Submit the pages found, best first.",
                  {"type": "object", "properties": {"reports": {"type": "array", "items": item}},
                   "required": ["reports"], "additionalProperties": False}, submit_reports)]

    def collect(resp: dict) -> None:
        for o in resp.get("output", []):
            if o.get("type") == "web_search_call":
                searches.append((o.get("action") or {}).get("query"))

    run = run_agent(client, orchestrator.MODEL, INSTRUCTIONS.format(n=MAX_REPORTS, kinds=", ".join(KINDS), searches=MAX_SEARCHES,
                                                                       reads=MAX_READS), task, tools,
                    14, budget_usd, effort="low", tag=f"find {city_id} {corner or 'projects'}",
                    required=("submit_reports",), governor=True, server_tools=[{"type": "web_search"}],
                    include=("web_search_call.results",), on_response=collect)
    # pages Muse Spark opened and that name the city but were never submitted: listed apart, never as found reports
    named = re.search(r"\(([^)]+)\)", city.get("agency") or "")
    too_old = {r["url"] for r in refused if str(r.get("why", "")).startswith("published in")}
    unsubmitted = [u for u in opened if u not in {k["url"] for k in kept} and u not in too_old and (
        _mentions(orchestrator.text_of(u) or "", city["name"]) or (named and _mentions(orchestrator.text_of(u) or "", named.group(1))))]
    return {"city": city_id, "corner": corner, "task": task, "reports": kept, "refused": refused, "opened_not_submitted": unsubmitted,
            "searches": [s for s in searches if s], "pages_read": len(reads), "usd": round(run.usd, 4),
            "stopped": run.stopped}


def find_projects(city_id: str, client, budget_usd: float = 0.25, intake_usd: float = 0.20,
                  max_pages: int = 3) -> dict:
    """Find the agency's project pages, then read their single-intersection projects (intake.extract)."""
    from . import intake
    found = find(city_id, client, budget_usd=budget_usd)
    # the agency's own pages first, then the other kept pages, then pages it opened without submitting them: intake
    # checks every project on them word for word, so a page that lists none costs a little and adds nothing
    first = ("project list", "agency page", "study or plan")
    kept = sorted(found["reports"], key=lambda r: r.get("kind") not in first)
    lists = list(dict.fromkeys([r["url"] for r in kept] + found["opened_not_submitted"]))[:max_pages]
    got = intake.extract(lists, opendata.city(city_id)["name"], client, budget_usd=intake_usd) if lists else \
        {"projects": [], "refused": [], "unreadable": [], "usd": 0.0, "pages": []}
    return {**found, "read_for_projects": lists, "projects": got["projects"], "projects_refused": got["refused"],
            "completed_left_out": got.get("completed_left_out", 0),
            "usd": round(found["usd"] + got["usd"], 4), "usd_find": found["usd"], "usd_intake": got["usd"]}


def report_md(r: dict) -> str:
    head = f"Reports about {r['corner']}" if r.get("corner") else f"Published project pages in {r['city']}"
    out = [f"# {head}", "", f"Searches: {'; '.join(r['searches']) or 'none'}", ""]
    for x in r["reports"]:
        out += [f"- **{x['title']}** ({x['publisher']}{', ' + x['published'] if x.get('published') else ''}), {x['kind']}",
                f"  {x['url']}", f"  > {x['passage']}", f"  {x['what']}"]
    for x in r["refused"]:
        out.append(f"- refused: {x.get('url')}: {x['why']}")
    for x in r.get("projects") or []:
        out.append(f"- project: {x['text'][:200]}")
    out.append(f"\n${r['usd']} Meta API")
    return "\n".join(out)

