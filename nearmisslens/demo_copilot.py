"""The demo video (under 3 minutes), made from the real product: screen recordings of the Junction Safety Copilot, the intake
page and the near-miss viewer, plus title cards, narrated by a local open-source voice (Kokoro, Apache-2.0).
Every number spoken comes from the result files in validation/; nothing is staged.

    uv run nml demo --copilot     # needs the app's cached briefs (nml brief ...) and the viewer data (nml export)"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import demo, democharts
from .config import ROOT, SETTINGS
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


def _bench(name: str) -> dict:
    p = RESULTS_DIR / "bench" / name
    return json.loads(p.read_text()) if p.exists() else {}


def hero() -> dict:
    """The opening junction, chosen from the results, not by hand: the plan-gap intersection with the most injury
    crashes in a city screen whose brief has a fix drawing that passed the SAM 3.1 check."""
    from . import brief, citywide, letter, opendata
    from .countermeasures import load_cmf
    for city in citywide.cities():
        everyone = sorted(_bench(f"citywide_{city}.json").get("rows", []), key=lambda r: -(r.get("injury_crashes") or 0))
        for rank, r in enumerate(everyone, 1):
            if not r.get("plan_gap"):
                continue
            slug = "".join(ch if ch.isalnum() else "_" for ch in r["name"].lower())[:60]
            path = SETTINGS.runs_dir / "briefs" / slug / "brief.json"
            f = json.loads(path.read_text()) if path.exists() else {}
            if not (f.get("illustration") or {}).get("check_passed"):
                continue
            d = f["dossier"]
            fx = brief.fix_options(d, load_cmf())
            top = next(o for o in fx["options"] if not o.get("verify_on_site"))
            area = next((o["area"] for o in letter.offices(d["lat"], d["lon"]) if o.get("area")), None)
            return {"name": r["name"], "spoken": r["name"].replace("&", "and") + (f", {area}" if area else ""),
                    "rank": rank, "of": len(everyone), "city": city, "city_name": opendata.city(city)["name"],
                    "area": area, "slug": slug, "fix_image": (f.get("illustration") or {}).get("image"),
                    "q": {"address": f["junction"], "lat": d["lat"], "lon": d["lon"]},
                    "injury": d["crashes"]["injury_crashes"], "peds": d["crashes"].get("pedestrian_injured", 0),
                    "harm_m": fx["harm"]["usd_per_year"] / 1e6, "top": top,
                    "last_project": max((p["year"] for p in d["plans"]["projects"] if isinstance(p.get("year"), int)),
                                        default=None)}
    raise FileNotFoundError("no screened junction has a brief with a checked fix drawing (nml citywide, nml brief)")


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
            verdict = "passed" if g["passed"] else ("failed the placebo" if g["rule_met"] else "not shown")
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
    labels = {"lpi": "NYC leading pedestrian intervals", "turn_calming": "NYC turn calming"}
    return [{"label": labels.get(k, k.replace("T13_", "").replace(":", " ").replace("_", " ")),
             "ungated": v.get("ungated", "?"), "gated": v.get("gated", "?")} for k, v in out.items()]


def script() -> list[Scene]:
    h = hero()
    cw = _bench(f"citywide_{h['city']}.json").get("summary", {})
    fr = _bench("fresh.json").get("pooled", {})
    rs = _bench("fresh_reseed.json").get("pooled", {})
    pet0 = fr.get("v0", {}).get("pet<=1.5", {}).get("f1")
    pet1 = rs.get("reseed", {}).get("pet<=1.5", {}).get("f1")
    lpi, turn, sea = _gate("T11", "lpi"), _gate("T11", "turn_calming"), _gate("T13_seattle", "lpi")
    fake = _bench("experiment_T12.json").get("summary", {})
    agents = [r for r in _bench("experiment_T12_agents_muse-spark-open.json").get("runs", [])
              if r.get("stopped") == "finish_tool" and r.get("claim")]
    top = h["top"]
    scenes = [
        Scene("hook", f"{h['spoken']}. {h['injury']} injury crashes in five years, "
                      f"{'the most' if h['rank'] == 1 else 'among the most'} of {h['city_name']}'s "
                      f"{h['of']} priority intersections. {h['peds']} pedestrians hurt. In the federal "
                      f"government's own values, that harm costs {h['harm_m']:.1f} million dollars a year. The city's "
                      f"records show no safety work here since {h['last_project']}.", "chart", target="hook",
              q={"aerial": str(Path(h["fix_image"]).with_name("aerial.jpg")),
                 "title": f"{h['name']}{', ' + h['area'] if h['area'] else ''}",
                 "lines": [f"{h['injury']} injury crashes in five years, the most of {h['of']} priority intersections",
                           f"{h['peds']} pedestrians hurt", f"${h['harm_m']:.1f} million a year in harm (U.S. DOT values)",
                           f"last recorded safety work: {h['last_project']}"]}),
        Scene("brief", "Ask about any corner. Agents on Meta's models pull the police record and the city's past "
                       "projects, and rank federal safety fixes by crashes prevented and dollars saved.", "app", target=h["q"]["address"], q=h["q"],
              caption="Official record, ranked fixes with their dollar value, a checked brief"),
        Scene("fix", f"Muse Image draws the top fix on the aerial photo, and SAM 3.1 checks it was really drawn. Refuge "
                     f"islands here would prevent about {top['expected_crashes_avoided_per_year']} pedestrian injury "
                     f"crashes a year.", "image",
              target=h["fix_image"], caption="Muse Image + SAM 3.1: the fix on the real junction (AI illustration, not a design)"),
        Scene("gates", "But why trust an AI? Here every claim meets a gate that tries to disprove it with public data: "
                       "numbers against the record, drawings against SAM, and 'this fix works' against the city's own "
                       "history.", "chart", target="gates"),
        Scene("measured", f"So we tested the cities' own installs. New York's leading pedestrian intervals passed: "
                          f"pedestrian injury crashes fell {-lpi['effect']} percent against intersections treated later, "
                          f"and a fake earlier date shows nothing. Turn calming failed: a simple before-and-after credits "
                          f"it with {-turn['naive']} percent, but crashes were already falling before the work began. The "
                          f"same test, unchanged, in Seattle: {-sea['effect']} percent, passed. Five other programs did not.",
                          "chart", target="forest", q={"rows": _forest_rows()}),
    ]
    if agents:
        un = [r for r in agents if not r["gated"] and r["fake"]]
        ga = [r for r in agents if r["gated"] and r["fake"]]
        uc, gc = (sum(r["claim"]["claim"] != "no_evidence" for r in x) for x in (un, ga))
        real = _analyst_real()
        t14 = _bench("experiment_T14a.json").get("designs", {})
        cal = max((v["calibrated_false_passes"] for v in t14.values()), default=None)
        rank = (_bench("study_T11.json").get("gates", {}).get("lpi", {}).get("fake_rank") or {}).get("rank")
        scenes.append(Scene(
            "analyst", "We gave an AI analyst, Muse Spark Open, programs to judge blind, writing its own code. Alone, it "
                       "missed New York's pedestrian intervals, credited two programs the data doesn't support, and "
                       f"contradicted itself once. The gate fixed all of that. But it let {gc} of {len(ga)} fake programs "
                       "through, so we tested the tester: a stricter gate cuts false passes to "
                       f"{cal} in a hundred, and shows New York's effect is less certain than it looked"
                       + (f", stronger than {round(100 * (1 - rank))} percent of fakes" if rank is not None else "")
                       + ". We report both.", "chart", target="analyst",
            q={"ungated": (uc, len(un)), "gated": (gc, len(ga)), "real": real}))
    else:
        scenes.append(Scene(
            "analyst", f"And on {fake.get('gate', {}).get('programs')} fake programs, where nothing was installed, a "
                       f"simple before-and-after found an effect {round(100 * fake.get('naive', {}).get('rate', 0))} "
                       f"percent of the time; the gate, {100 * fake.get('gate', {}).get('rate', 0):.1f}.", "card",
            "Fake programs", "Fake programs credited with a reduction: naive "
            f"{100 * fake.get('naive', {}).get('rate', 0):.1f}%, gate {100 * fake.get('gate', {}).get('rate', 0):.1f}%."))
    scenes += [
        Scene("map", f"Each red dot is a priority intersection with many injury crashes and nothing done, "
                     f"{cw.get('plan_gap')} of them, and this panel shows what has worked in the city.",
              "app", target="", caption="What has worked here: each program tested on the city's own crash records"),
        Scene("letter", "Then it drafts a checked letter to the council member and community board, found from the "
                        "city's district maps. The resident sends it.", "letter", target=h["q"]["address"], q=h["q"],
              caption="A checked letter to the council district and community board, drafted from the record"),
        Scene("video", "Where drone video exists, SAM 3.1 tracks every road user and measures near misses before "
                       "crashes happen.",
              "viewer", caption="SAM 3.1 near-miss measurement on drone video (FLUID dataset, CC BY 4.0)"),
        Scene("open", "Meta's open weights run the analyst, the briefs and the letters: Muse Spark Open on Baseten, and "
                      "Muse Glimmer on a Modal GPU.", "card", "Meta models throughout",
              "SAM 3.1 · Muse Spark · Muse Wonder · Muse Image · Voice Transcribe · Muse Spark Open · Muse Glimmer"),
        Scene("end", "NearMissLens. Every claim tested before it is shown. Built during the hackathon; engineers decide.",
              "card", "NearMissLens", "Every claim tested before it is shown. Open source, built during the hackathon."),
    ]
    return scenes


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


def _record_letter(url: str, name: str, seconds: float, work: Path) -> Path:
    def steps(page, base):
        page.goto(url)
        page.wait_for_selector("#ltr", timeout=180000)
        page.click("#ltr")
        page.wait_for_selector("#ltrtxt", timeout=180000)
        page.evaluate("document.getElementById('ltrout').scrollIntoView()")
        for _ in range(int(seconds)):
            page.evaluate("document.getElementById('ltrtxt').scrollBy(0, 40)")
            page.wait_for_timeout(1000)
    return demo.record(url, name, steps, work / "rec")


def _record_app(url: str, name: str, seconds: float, work: Path, scroll: bool) -> Path:
    def steps(page, base):
        page.goto(url)
        page.wait_for_timeout(1500)
        if scroll:
            page.wait_for_selector("#out .card h2", timeout=180000)
            page.evaluate("document.getElementById('out').scrollIntoView()")
            page.wait_for_timeout(1500)
            for _ in range(int(seconds)):
                page.evaluate("document.getElementById('side').scrollBy(0, 70)")
                page.wait_for_timeout(1000)
        else:
            page.wait_for_timeout(int(seconds * 1000))
    return demo.record(url, name, steps, work / "rec")


def render(out: Path | None = None) -> Path:
    from .app import serve as app_serve
    from .serve import serve as intake_serve
    work = SETTINGS.data_dir / "work" / "demo_copilot"
    work.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=app_serve, kwargs={"port": 8790}, daemon=True).start()
    threading.Thread(target=intake_serve, args=("test_sam", 8791, "muse-spark-1.3-contributor"), daemon=True).start()
    srv, docs = demo._serve(demo.DOCS)
    time.sleep(3)
    clips = []
    try:
        for k, s in enumerate(script()):
            from . import voicestudio
            mine = voicestudio.take(k, s.name, s.narration)  # the narrator's own recording, if it matches the line
            wav = mine or work / f"{k:02d}_{s.name}.wav"
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
            elif s.kind in ("app", "letter"):
                from urllib.parse import quote
                q = s.q or {"address": s.target}
                if s.target:  # build the brief (and letter) once before recording, so the scene shows them
                    import httpx
                    httpx.post("http://127.0.0.1:8790/brief", json=q, timeout=600)
                    if s.kind == "letter":
                        httpx.post("http://127.0.0.1:8790/letter", json=q, timeout=600)
                url = "http://127.0.0.1:8790/" + (f"?q={quote(s.target)}" if s.target else "") + \
                    (f"&lat={q['lat']}&lon={q['lon']}" if s.target and "lat" in q else "")
                webm = (_record_letter(url, s.name, secs + 3, work) if s.kind == "letter"
                        else _record_app(url, s.name, secs + 3, work, scroll=bool(s.target)))
                seg = demo.Segment(webm, secs, s.caption, skip=demo.LOAD_S)
            elif s.kind == "intake":
                import httpx
                httpx.post("http://127.0.0.1:8791/ask_text", content=s.target.encode(), timeout=600)  # warm the answer

                def steps(page, base, text=s.target, secs=secs):
                    page.goto("http://127.0.0.1:8791/")
                    page.fill("#txt", text)
                    page.click("#send")
                    page.wait_for_selector(".verdict", timeout=180000)
                    page.wait_for_timeout(int(secs * 1000))
                webm = demo.record("http://127.0.0.1:8791/", s.name, steps, work / "rec")
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
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in clips))
    out = out or SETTINGS.runs_dir / "demo" / "nearmisslens_copilot_demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
                   check=True)
    print(f"{out}: {demo._duration(out):.1f} s")
    return out
