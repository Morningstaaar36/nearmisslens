"""The demo video (under 3 minutes), made from the real product: screen recordings of the copilot (the static site in
docs/, built by nml pages) opening the safety engineer's case for the city's worst corner, the near-miss viewer, and
charts drawn from the result files. The narration is the author's own voice (nml voice-studio); Kokoro is only a guide
voice for timing drafts. Every number spoken comes from the engineer's report or validation/; nothing is staged.

    uv run nml pages              # the reports the scenes open
    uv run nml demo --copilot"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import demo, democharts
from .config import ROOT, SETTINGS, resolve
from .evaluate import RESULTS_DIR

VOICE = "af_heart"
PAD_S = 0.7


@dataclass
class Scene:
    name: str
    narration: str
    kind: str  # "card", "app", "letter", "intake", "viewer", "image"
    title: str = ""
    target: str = ""
    caption: str = ""
    q: dict | None = None  # the app request (address and coordinates) for "app" and "letter" scenes


def _plain(name: str) -> str:
    from . import letter
    return letter._plain(name)


def _bench(name: str) -> dict:
    p = RESULTS_DIR / "bench" / name
    return json.loads(p.read_text()) if p.exists() else {}


def hero(city: str | None = None) -> dict:
    """The opening corner, chosen from the results, not by hand: the worst corner of the first screened city, with the
    numbers of the engineer's saved report for it (nml pages / engineer.precompute)."""
    from . import citywide, engineer, opendata, pages
    for c in ([city] if city else citywide.cities()):
        rows = sorted(_bench(f"citywide_{c}.json").get("rows", []), key=lambda r: -(r.get("injury_crashes") or 0))
        if not rows:
            continue
        r = rows[0]
        path = SETTINGS.runs_dir / "engineer" / c / f"{engineer.slug(r['name'])}.json"
        if not path.exists():
            raise FileNotFoundError(f"no engineer report for {r['name']}; run nml pages")
        rep = json.loads(path.read_text())
        f = rep["findings"]
        cr, fx, who = f["choose_fixes"]["crashes"], f["choose_fixes"], f["who_must_act"]
        # the over-represented pattern with the most excess crashes over the city's share
        over = sorted(f["root_cause"].get("over_represented") or [], key=lambda t: -(t["share"] - t["city_share"]))
        low = [o for o in fx.get("options", []) if o.get("scale") == "low-cost"]
        offices = [x["party"] for x in who["requesters"]]
        projects = [p["year"] for p in f["test_programs"].get("projects_here", []) if isinstance(p.get("year"), int)]
        aerial = pages._brief_dir(r["name"]) / "aerial.jpg"
        return {"name": r["name"], "slug": engineer.slug(r["name"]), "city": c, "of": len(rows),
                "city_name": opendata.city(c)["name"], "spoken": r["name"].replace("&", "and"),
                "aerial": str(aerial) if aerial.exists() else None,
                "injury": cr.get("injury_crashes"), "peds": cr.get("pedestrian_injured", 0),
                "harm_m": fx["harm"]["usd_per_year"] / 1e6 if fx.get("harm") else None,
                "last_project": max(projects) if projects else None, "pattern": over[0] if over else None,
                "top": low[0] if low else None, "owners": who["owners"], "offices": offices,
                "letter": bool(f["draft_request"].get("letter")), "seconds": rep["seconds"]}
    raise FileNotFoundError("no screened city (nml citywide)")


def _gate(study: str, key: str) -> dict:
    """A program's causal-gate result from a saved study: the primary effect, the gate and the naive estimate (T12)."""
    tr = _bench(f"study_{study}.json")
    g = tr.get("gates", {}).get(key, {})
    m = tr.get("runs", {}).get(g.get("primary", ""), {}).get(g.get("outcome", "pedestrian"), {}) or {}
    naive = next((r["naive"] for r in _bench("experiment_T12.json").get("real", []) if r["program"] == key and study == "T11"), {})
    pl = tr.get("runs", {}).get((g.get("placebos") or [""])[0], {}).get(g.get("outcome", "pedestrian"), {}) or {}
    def pct(t):  # percent change, rounded half away from zero (-32.5 -> -33), as the README writes it
        if t is None:
            return None
        v = round(100 * (t - 1), 1)  # the one-decimal change the results file reports
        return int(abs(v) + 0.5) * (1 if v >= 0 else -1)
    return {"passed": g.get("passed"), "effect": pct(m.get("theta")), "sites": m.get("sites"),
            "ci": [pct(v) for v in m.get("ci95", [])], "naive": pct(naive.get("theta")), "placebo": pct(pl.get("theta")),
            "cmf": (g.get("brief_cmf") or [{}])[0].get("cmf")}


def _forest_rows() -> list[dict]:
    """Every registered program's gate result for the forest plot, passed ones first."""
    from . import opendata, treatments
    rows = []
    for res in treatments.results():
        if res["id"].startswith("auto_"):
            continue
        for key, g in res.get("gates", {}).items():
            m = res["runs"][g["primary"]][g["outcome"]] or {}
            nv = (res.get("naive") or {}).get(key, {}).get(g["outcome"]) or {}
            city = (opendata.city(res["city"]) or {}).get("name", res["city"])
            verdict = "worked" if g["passed"] else ("earlier trend" if g["rule_met"] else "not shown")
            name = g["treatment"].replace("Leading Pedestrian Interval signals", "leading pedestrian intervals")
            city = {"New York City": "New York", "Washington DC": "Washington"}.get(city, city)
            rows.append({"label": f"{city}: {name}", "passed": g["passed"], "verdict": verdict,
                         "effect": m.get("change_pct"), "ci": [round(100 * (v - 1), 1) for v in m["ci95"]] if m.get("ci95") else None,
                         "naive": nv.get("change_pct")})
    return sorted(rows, key=lambda r: (not r["passed"], r["verdict"]))


def _analyst_real() -> list[dict]:
    """The analyst's claims on real programs, without and with the gate (New York and other cities)."""
    runs = []
    for f in ("experiment_T12_agents_muse-spark-open.json", "experiment_T12_agents_muse-spark-open_real.json"):
        runs += [r for r in _bench(f).get("runs", []) if r.get("stopped") == "finish_tool" and r.get("claim") and not r["fake"]]
    out = {}
    for r in runs:
        c = r["claim"]
        out.setdefault(r["program_key"], {})["gated" if r["gated"] else "ungated"] = \
            f"{c['claim'].replace('_', ' ')} ({c['effect_pct']:+.0f}%)" if c["claim"] != "no_evidence" else "no evidence"
    labels = {"lpi": "New York pedestrian intervals", "turn_calming": "New York turn calming",
              "T13_seattle:lpi": "Seattle pedestrian intervals", "T13_dc:lpi": "Washington pedestrian intervals",
              "T13_nyc:speed_humps": "New York speed humps", "T13_nyc:enhanced_crossings": "New York enhanced crossings",
              "T13_sf:continental_crosswalks": "San Francisco crosswalks"}
    return [{"label": labels.get(k, k.replace("T13_", "").replace(":", " ").replace("_", " ")),
             "ungated": v.get("ungated", "?"), "gated": v.get("gated", "?")} for k, v in out.items()]


def _owners_spoken(owners: list[dict]) -> str:
    def short(party: str) -> str:
        m = re.search(r"\(([A-Z][A-Za-z ]+)\)", party)  # "the New York State Department ... (NYSDOT)" -> NYSDOT
        return m.group(1) if m else party.replace("the ", "", 1)
    parts = [f"{short(o['party'])} for {o['roads'][0].split(' (')[0]}" for o in owners]
    return ", and ".join(parts)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _office_spoken(office: str) -> str:
    m = re.match(r"Council Member, District (\d+)", office)
    return f"the council member for District {m.group(1)}" if m else office


def script() -> list[Scene]:
    h = hero()
    lpi, turn, sea = _gate("T11", "lpi"), _gate("T11", "turn_calming"), _gate("T13_seattle", "lpi")
    agents = [r for r in _bench("experiment_T12_agents_muse-spark-open.json").get("runs", [])
              if r.get("stopped") == "finish_tool" and r.get("claim")]
    top, pat = h["top"], h["pattern"]
    usd = lambda v: f"{v / 1e6:.1f} million dollars" if v >= 1e6 else f"{round(v, -3):,.0f} dollars"
    case = {"slug": h["slug"]}
    scenes = [
        Scene("hook", f"{h['spoken']}, in {h['city_name']}. {h['injury']} injury crashes in five years, the most of the "
                      f"city's {h['of']} priority intersections, about {h['harm_m']:.1f} million dollars a year in harm. "
                      + (f"No safety work recorded since {h['last_project']}. " if h["last_project"] else "")
                      + "Who should fix it, with what, and has that fix worked here before?", "chart", target="hook",
              q={"aerial": h["aerial"], "title": h["name"],
                 "lines": [f"{h['injury']} injury crashes in five years, the most of {h['of']} priority intersections",
                           f"{h['peds']} pedestrians hurt", f"${h['harm_m']:.1f} million a year in harm (U.S. DOT values)"]
                          + ([f"last recorded safety work: {h['last_project']}"] if h["last_project"] else [])}),
        Scene("case", "NearMissLens is a safety engineer built on Meta's models. Give it a city and it screens every "
                      "priority corner, opens the worst, and writes the case. Every sentence names its receipt: the "
                      "dataset, the date, the check it passed. A sentence that doesn't match its receipt is refused.",
              "case", q={**case, "section": 0}, caption="The case, sentence by sentence, each with its receipt"),
    ]
    if pat:
        scenes.append(Scene("pattern", f"What do the crashes here have in common? {treat_pct(pat['share'])} percent "
                                       f"{pat['phrase']}, against {treat_pct(pat['city_share'])} percent at the city's "
                                       "other priority corners. It says 'have in common', never 'caused'.",
                            "case", q={**case, "section": 1}, caption="Patterns tested against the city's priority corners"))
    scenes.append(Scene("tried", "What has the city already tried? Each program is tested on its own crash records, "
                                 "against places treated later, with a fake earlier date that must show nothing. New "
                                 f"York's leading pedestrian intervals: {-lpi['effect']} percent fewer pedestrian injury "
                                 f"crashes. Turn calming looks like a {-turn['naive']} percent drop, but crashes were already "
                                 f"falling before the work. Seattle: {-sea['effect']} percent fewer, the same test, unchanged.",
                        "chart", target="forest", q={"rows": _forest_rows()}))
    if top:
        scenes.append(Scene("fix", f"The fix the record supports here: {_plain(top['countermeasure'])}, about "
                                   f"{top['expected_crashes_avoided_per_year']:g} fewer crashes a year, worth "
                                   f"{usd(top['harm_avoided_usd_per_year'])} a year, from the federal study that fits "
                                   "this signalized corner.", "case", q={**case, "section": 3},
                            caption="Federal countermeasures, priced only where a study fits the corner"))
    if h["owners"]:
        scenes.append(Scene("who", f"Who must act? {'Two owners' if len(h['owners']) == 2 else 'The owner'}: "
                                   f"{_owners_spoken(h['owners'])}. "
                                   + ("A request to the city alone would miss the state. " if len(h["owners"]) > 1 else "")
                                   + (_cap(' and '.join(_office_spoken(o) for o in h['offices'])) + " can push for it."
                                      if h["offices"] else ""),
                            "case", q={**case, "section": 4}, caption="Road owners from the state inventory; offices from district maps"))
    scenes.append(Scene("letter", "Then it drafts the request to the owners, copying the offices, and checks every number "
                                  "before you see it. You send it; NearMissLens sends nothing.", "case",
                        q={**case, "section": 5, "letter": h["letter"]}, caption="The request letter, checked number by number"))
    if agents:
        un = [r for r in agents if not r["gated"] and r["fake"]]
        ga = [r for r in agents if r["gated"] and r["fake"]]
        uc, gc = (sum(r["claim"]["claim"] != "no_evidence" for r in x) for x in (un, ga))
        rank = (_bench("study_T11.json").get("gates", {}).get("lpi", {}).get("fake_rank") or {}).get("rank")
        scenes.append(Scene(
            "analyst", "Why trust it? We gave an AI analyst, Muse Spark Open, the programs blind. Alone, it missed New "
                       "York's pedestrian intervals and credited two programs the data doesn't support. The gate fixed "
                       f"that, but let {gc} of {len(ga)} fake programs through, so we tested the tester and report "
                       "where it is weak"
                       + (f": New York's effect beats {round(100 * (1 - rank))} percent of fake programs, not all of them"
                          if rank is not None else "") + ".", "chart", target="analyst",
            q={"ungated": (uc, len(un)), "gated": (gc, len(ga)), "real": _analyst_real()}))
    scenes += [
        Scene("video", "Where drone video exists, SAM 3.1 tracks the road users and measures near misses before "
                       "crashes happen.", "viewer", caption="SAM 3.1 near-miss measurement on drone video (FLUID dataset, CC BY 4.0)"),
        Scene("end", f"NearMissLens. {h['of']} corners, each case built from public records in seconds, every claim "
                     "with its receipt. Open source, built during the hackathon. Engineers decide.", "card", "NearMissLens",
              "A safety engineer that shows its receipts. Muse Spark Open on Baseten, Muse Spark, SAM 3.1, Muse Image."),
    ]
    return scenes


def treat_pct(share: float) -> int:
    from .treatments import pct
    return pct(100 * share)


_PIPE = []


def narrate(text: str, out: Path) -> float:
    """Kokoro speech for one scene; returns its length in seconds."""
    import soundfile as sf
    if not out.exists():
        if not _PIPE:
            from kokoro import KPipeline
            _PIPE.append(KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M"))
        parts = [a.numpy() if hasattr(a, "numpy") else a for _, _, a in _PIPE[0](text, voice=VOICE)]
        sf.write(out, np.concatenate(parts), 24000)
    return demo._duration(out)


def _record_case(base: str, q: dict, name: str, seconds: float, work: Path) -> Path:
    """Open the copilot on a corner's case and hold one section in view, scrolling slowly through it."""
    def steps(page, _base):
        page.goto(f"{base}/#{q['slug']}")
        page.wait_for_selector("h2.corner", timeout=60000)
        page.wait_for_timeout(int(demo.LOAD_S * 1000))
        target = "#letter" if q.get("letter") and q.get("section") == 5 else None
        page.evaluate("([n, t]) => { const el = t ? document.querySelector(t) : document.querySelectorAll('section.step')[n];"
                      " if (el) { el.scrollIntoView({block: 'start'}); window.scrollBy(0, -12); } }", [q.get("section", 0), target])
        # the case itself scrolls slowly through its sentences; every other scene holds its section in view
        step = 22 if q.get("section", 0) == 0 and not target else 0
        for _ in range(int(seconds)):
            page.wait_for_timeout(1000)
            if step:
                page.mouse.wheel(0, step)
    return demo.record(base, name, steps, work / "rec", zoom=1.6)


def render(out: Path | None = None) -> Path:
    from . import pages
    work = SETTINGS.data_dir / "work" / "demo_copilot"
    work.mkdir(parents=True, exist_ok=True)
    if not (pages.DOCS / "data" / "index.json").exists():
        raise FileNotFoundError("the static site is not built; run nml pages")
    srv, docs = demo._serve(demo.DOCS)
    site, base = demo._serve(pages.DOCS)
    time.sleep(1)
    clips = []
    try:
        for k, s in enumerate(script()):
            from . import voicestudio
            mine = voicestudio.take(k, s.name, s.narration)  # the narrator's own recording, if it matches the line
            import hashlib
            wav = mine or work / f"{k:02d}_{s.name}_{hashlib.sha256(s.narration.encode()).hexdigest()[:10]}.wav"
            secs = (demo._duration(wav) if mine else narrate(s.narration, wav)) + PAD_S
            if s.kind == "card":
                seg = demo.card(s.title, s.caption or s.target, work / f"card_{s.name}", work, secs, credit="")
            elif s.kind == "chart":
                png = work / f"chart_{s.name}.png"
                q = s.q or {}
                if s.target == "hook":
                    democharts.hook(Path(q["aerial"]), q["title"], q["lines"], png, work)
                elif s.target == "gates":
                    democharts.gates(png, work)
                elif s.target == "forest":
                    democharts.forest(q["rows"], png, work)
                else:
                    democharts.analyst(tuple(q["ungated"]), tuple(q["gated"]), q["real"], png, work)
                seg = demo.Segment(png, secs, s.caption)
            elif s.kind == "image":
                seg = demo.Segment(Path(s.target), secs, s.caption, caption_top=True)
            elif s.kind == "case":
                webm = _record_case(base, s.q, s.name, secs + 2, work)
                seg = demo.Segment(webm, secs, s.caption, skip=demo.LOAD_S)
            else:  # the near-miss viewer: 3D replay of the worst conflict at the held-out junction
                key = "heldout_sam"
                view = json.loads((demo.DOCS / "data" / f"{key}.json").read_text())
                name, _, steps = next(x for x in demo._scenes(key, view) if x[0] == "replay")
                webm = demo.record(docs, s.name, steps, work / "rec")
                seg = demo.Segment(webm, secs, s.caption, skip=demo.LOAD_S)
            silent = demo._to_clip(seg, work / f"v{k:02d}.mp4", work)
            clip = work / f"part{k:02d}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(wav), "-filter_complex",
                            f"[1:a]apad=whole_dur={secs}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                            "-shortest", str(clip)], check=True)
            clips.append(clip)
            print(f"scene {s.name}: {secs:.1f} s", flush=True)
    finally:
        srv.shutdown()
        site.shutdown()
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in clips))
    out = out or SETTINGS.runs_dir / "demo" / "nearmisslens_copilot_demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
                   check=True)
    print(f"{out}: {demo._duration(out):.1f} s")
    return out
