"""The demo video for "Before you commit" (under 3 minutes), made from the real product: screen recordings of the
static site (docs/, the saved registered runs) and title cards. Every number spoken is read from validation/ results
here, never typed into the script. The narration is the author's own voice where a take exists (nml voice-studio);
Kokoro is only a guide voice for the lines not yet recorded.

    uv run nml demo --desk           # runs/demo/nearmisslens_desk_demo.mp4"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

from . import demo
from .config import ROOT, SETTINGS
from .demo_copilot import PAD_S, Scene, narrate
from .evaluate import RESULTS_DIR


def _load(name: str) -> dict:
    p = RESULTS_DIR / "bench" / name
    return json.loads(p.read_text()) if p.exists() else {}


def _spec(run: str) -> dict:
    return json.loads((ROOT / "validation" / "experiments" / f"{run}.json").read_text())


def _words(n: int) -> str:
    small = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
    return small[n] if 0 <= n < len(small) else str(n)


def _cents(usd: float) -> str:
    return f"{round(usd * 100)} cents"


def facts() -> dict:
    """The numbers the narration speaks, from the registered results."""
    from .baseline_desk import summary as t24_summary
    from .check_runs import summary as check_summary
    from .review import run_summary
    reviews = next(r for r in ("T28", "T27", "T26") if _load(f"experiment_{r}.json"))
    rv = run_summary(_load(f"experiment_{reviews}.json"), _spec(reviews))
    cases = _load(f"experiment_{reviews}.json")["cases"]
    t25 = check_summary(_load("experiment_T25.json"), "T25")
    t24 = t24_summary(_load("experiment_T24.json"))
    out = {"reviews_run": reviews, "rv": rv, "t25": t25, "t24": t24,
           "cities": len({c.get("city_id") or c.get("city") for c in cases}),
           "in_place": next((c for c in cases if (c.get("appraisal") or {}).get("in_place")), None),
           "argued": max(cases, key=lambda c: len(c.get("objections") or [])) if cases else None}
    if _load("experiment_T30c.json"):
        from .intake import run_summary as intake_summary
        out["t30"] = intake_summary(_load("experiment_T30c.json"), _spec("T30c"))
    run = next((r for r in ("T29b", "T29") if _load(f"experiment_{r}.json")), None)
    if run:  # the latest registered program run
        from .portfolio import run_summary as program_summary
        prog = _load(f"experiment_{run}.json")
        out["t29"] = program_summary(prog, _spec(run))
        out["program"] = prog["programs"][0]
    return out


def _clean_check() -> str | None:
    """The saved check to show, read from the results: a published real input whose claims are all the source's own
    sentences (T25 also checked some of the desk's own sentences, fixed after) and whose letter needs no correction.
    The false-statement control is not shown: T25's review found it had drifted to another corner."""
    import re
    from . import pages
    p = pages.DOCS / "data" / "checks.json"
    if not p.exists():
        return None
    cases = [c for c in json.loads(p.read_text())["cases"] if c.get("status") == "published" and not c.get("control")
             and not c.get("letter_correction")]
    own = lambda c: any(re.search(r"in police records since", x.get("claim", "")) for x in c.get("claims") or [])
    good = [c for c in cases if c.get("claims") and not own(c)]
    return (good or cases or [{}])[0].get("id")


def script(f: dict | None = None) -> list[Scene]:
    f = f or facts()
    rv, t25, t24 = f["rv"], f["t25"], f["t24"]
    ip = f["in_place"] or {}
    ipc = (ip.get("appraisal") or {}).get("in_place") or {}
    scenes = [
        Scene("open", "Every week a news story calls an intersection deadly, or someone asks for a fix. Before an agency "
                      "spends money, an engineer has to check the proposal against the city's own crash record. "
                      "NearMissLens does that due diligence with Meta's models, and code checks every step.",
              "card", "Before you commit", caption="Due diligence on a street-safety project before the money is spent"),
        Scene("memo", f"Here a proposal from {ip.get('city_name') or 'a city'}: {ip.get('input', '')[:120]}. Muse Spark "
                      "registers it against the federal list of proven countermeasures and investigates the corner with "
                      "checked tools. Then code, not the model, sets the verdict: reconsider. The city's own records "
                      f"show a {(ipc.get('countermeasure') or 'fix').lower()} is already there.",
              "page", target="memo", q={"route": "review", "match": ip.get("id")},
              caption="Code sets the verdict from the receipts; the model cannot change it"),
        Scene("premortem", "A second model family, Muse Spark Open on Baseten, writes the pre-mortem: the strongest case "
                           "against the decision. It must rest every objection on a fact in the receipts, and code keeps it "
                           "only if that fact is really there. The memo has to answer every one.",
              "page", target="premortem", q={"route": "review", "match": (f["argued"] or {}).get("id")},
              caption="Muse Spark Open argues against the verdict; code checks each objection's fact"),
        Scene("results", f"We registered every test before running it. {_words(rv['inputs']).capitalize()} real proposals "
                         f"from {_words(f['cities'])} cities' plans: {_words(rv['published'])} memos, every one on the corner proposed, "
                         f"{rv['objections_kept']} checked objections, about {_cents(rv['mean_usd'])} a review. "
                         "Independent testers broke earlier versions; what they found is fixed, and their reports "
                         "are kept as written.",
              "card", f"{rv['published']} of {rv['inputs']} memos, {rv['objections_kept']} checked objections",
              caption=f"Registered run {f['reviews_run']}: rule met; ${rv['mean_usd']:.3f} a review"),
    ]
    if f.get("t30"):
        t = f["t30"]
        kept = sum(r["kept"] for r in t["rows"])
        scenes.append(Scene("intake", "An agency rarely has one proposal; it has a list on a web page. Give the page, and "
                                      "Muse Spark reads every project at an intersection, with the page's own status. Code "
                                      "keeps one only if its sentence is on the page and names both streets. On two "
                                      f"agencies' pages it found all {t['hand_found']} projects we had listed by hand, "
                                      f"{kept} in all, at about {_cents(t['mean_usd_per_readable_page'])} a page. Then "
                                      "every project is reviewed, and code ranks the list.",
                            "card", f"From the agency's page: {t['hand_found']} of {t['hand_projects']} projects found",
                            caption=f"nml intake, registered run T30c (after two runs that did not meet the rule)"))
    if f.get("t29"):
        t = f["t29"]
        scenes.append(Scene("program", f"Program review takes the whole list, reviews each proposal, and code ranks "
                                       f"them: build, check on site first, compare, study, or reconsider. On "
                                       f"{_words(t['programs'])} real lists from the agencies' own pages, "
                                       f"{t['reviewed']} of {t['proposals']} proposals were reviewed, each on its own "
                                       "corner. Most rest on fixes no federal study covers, and the memos say so "
                                       "instead of promising a number.",
                            "page", target="program", q={"route": "program"},
                            caption="A whole program, reviewed and ranked by code"))
    scenes += [
        Scene("check", f"The same desk checks claims. On {t25['inputs']} inputs nobody chose for it, all "
                       f"{_words(t25['published_real'])} real ones were published at the right corner, and all "
                       f"{t25['quotes_verified']} of their quotes were found on their pages. An off-topic page that names a "
                       "corner was refused.",
              "page", target="check", q={"route": "check", "match": _clean_check()},
              caption="Check a claim: every quote against its page, every number against the record"),
        Scene("gates", f"Why the gates matter: Muse Spark alone, with the same web search, cited {t24['quotes_absent']} "
                       f"quotes out of {t24['quotes_verified'] + t24['quotes_absent']} that are not on the page it cites. "
                       "With the gates, nothing is published until code has checked it.",
              "card", f"Alone: {t24['quotes_absent']} of {t24['quotes_verified'] + t24['quotes_absent']} quotes not on "
                      "their page", caption="Muse Spark alone (T24) against the desk with its gates"),
        Scene("close", "An engineer at the site can even speak the proposal: Muse Voice Transcribe takes it down, and "
                       "the same review runs. Every test is in the repository, met or not. It is live now: try a "
                       "proposal we held out, or bring your own.",
              "card", "Try it on your city's proposal", caption="nml review · nml portfolio · held-out sets in TESTING.md"),
    ]
    return scenes


def _steps(s: Scene, seconds: float):
    q = s.q or {}

    def run(page, base):
        page.goto(f"{base}/#{q.get('route', 'review')}")
        page.wait_for_selector("h2.corner", timeout=60000)
        page.wait_for_timeout(int(demo.LOAD_S * 1000))
        if s.target == "program":
            page.evaluate("() => { const d = [...document.querySelectorAll('details')].find(x => x.closest('section')"
                          " && /program/i.test(x.closest('section').textContent.slice(0, 60))); if (d) { d.open = true;"
                          " d.scrollIntoView({block: 'start'}); } }")
        elif q.get("match"):
            # open the saved case whose data id matches, by its summary text (the page lists cases in file order)
            page.evaluate("(m) => { const sec = [...document.querySelectorAll('section')].find(x => /^Saved (reviews|checks)/"
                          ".test((x.querySelector('h3') || {}).textContent || '')); if (!sec) return; const ds = "
                          "[...sec.querySelectorAll(':scope > details')]; const i = (window.__ids || []).indexOf(m); "
                          "const d = ds[i] || ds[0]; if (d) { d.open = true; d.scrollIntoView({block: 'start'}); } }",
                          q["match"])
        if s.target == "premortem":
            page.evaluate("() => { const h = [...document.querySelectorAll('details[open] h4')].find(x => "
                          "/Pre-mortem/.test(x.textContent)); if (h) h.scrollIntoView({block: 'start'}); }")
        for k in range(int(seconds)):
            page.wait_for_timeout(1000)
            if k >= 3:  # hold the verdict (or the opening of the section) in view first, then read down
                page.mouse.wheel(0, 30)
    return run


def _case_order(route: str) -> list[str]:
    from . import pages
    name = {"review": "reviews.json", "check": "checks.json"}.get(route)
    p = pages.DOCS / "data" / (name or "")
    return [c.get("id") for c in json.loads(p.read_text())["cases"]] if name and p.exists() else []


def render(out: Path | None = None) -> Path:
    from . import pages, voicestudio
    work = SETTINGS.data_dir / "work" / "demo_desk"
    work.mkdir(parents=True, exist_ok=True)
    site, base = demo._serve(pages.DOCS)
    time.sleep(1)
    clips = []
    try:
        for k, s in enumerate(script()):
            mine = voicestudio.take(k, s.name, s.narration)
            wav = mine or work / f"{k:02d}_{s.name}_{hashlib.sha256(s.narration.encode()).hexdigest()[:10]}.wav"
            secs = (demo._duration(wav) if mine else narrate(s.narration, wav)) + PAD_S
            if s.kind == "card":
                seg = demo.card(s.title, s.caption, work / f"card_{s.name}", work, secs, credit="")
            else:
                q = dict(s.q or {})
                ids = _case_order(q.get("route", ""))
                steps = _steps(s, secs + 2)

                def with_ids(page, b, steps=steps, ids=ids):
                    page.add_init_script(f"window.__ids = {json.dumps(ids)};")
                    steps(page, b)
                webm = demo.record(base, s.name, with_ids, work / "rec", zoom=1.5)
                seg = demo.Segment(webm, secs, s.caption, skip=demo.LOAD_S)
            silent = demo._to_clip(seg, work / f"v{k:02d}.mp4", work)
            clip = work / f"part{k:02d}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(wav), "-filter_complex",
                            f"[1:a]apad=whole_dur={secs}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                            "-shortest", str(clip)], check=True)
            clips.append(clip)
            print(f"scene {s.name}: {secs:.1f} s", flush=True)
    finally:
        site.shutdown()
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in clips))
    out = out or SETTINGS.runs_dir / "demo" / "nearmisslens_desk_demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
                   check=True)
    print(f"{out}: {demo._duration(out):.1f} s")
    return out
