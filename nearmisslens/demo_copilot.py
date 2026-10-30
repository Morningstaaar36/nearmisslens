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

from . import demo
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


HERO = "bruckner_boulevard___hunts_point_avenue"


def hero() -> dict:
    """The opening junction's numbers, from its stored brief: the record, the yearly harm and the top fix."""
    from . import brief
    from .countermeasures import load_cmf
    f = json.loads((SETTINGS.runs_dir / "briefs" / HERO / "brief.json").read_text())
    d = f["dossier"]
    fx = brief.fix_options(d, load_cmf())
    top = next(o for o in fx["options"] if not o.get("verify_on_site"))
    return {"name": f["junction"].split(",")[0], "spoken": f["junction"].split(",")[0].replace("&", "and"), "q": {"address": f["junction"], "lat": d["lat"], "lon": d["lon"]},
            "injury": d["crashes"]["injury_crashes"], "peds": d["crashes"].get("pedestrian_injured", 0),
            "harm_m": fx["harm"]["usd_per_year"] / 1e6, "top": top,
            "last_project": max((p["year"] for p in d["plans"]["projects"] if isinstance(p.get("year"), int)), default=None)}


def _bench(name: str) -> dict:
    p = RESULTS_DIR / "bench" / name
    return json.loads(p.read_text()) if p.exists() else {}


def script() -> list[Scene]:
    cw = _bench("citywide_nyc.json").get("summary", {})
    cw = {**cw, "injury_crashes_total": cw.get("injury_crashes_distinct", cw.get("injury_crashes_total")),
          "killed_total": cw.get("killed_distinct", cw.get("killed_total"))}
    c4 = _bench("complaints.json").get("summary", {})
    fr = _bench("fresh.json").get("pooled", {})
    rs = _bench("fresh_reseed.json").get("pooled", {})
    spark = c4.get("spark_checked", {})
    pet0 = fr.get("v0", {}).get("pet<=1.5", {}).get("f1")
    pet1 = rs.get("reseed", {}).get("pet<=1.5", {}).get("f1")
    h = hero()
    tr = _bench("treatments_nyc.json")
    lpi = tr.get("lpi_not_yet_treated", {}).get("pedestrian", {})
    plc = tr.get("lpi_placebo_same_sites_not_yet_treated", {}).get("pedestrian", {})
    drop, lo, hi = (round(100 * (1 - v)) for v in (lpi.get("theta", 1), lpi.get("ci95", [1, 1])[1], lpi.get("ci95", [1, 1])[0]))
    cmf = (tr.get("brief_cmf") or [{}])[0].get("cmf", 1)
    top = h["top"]
    return [
        Scene("hook", f"{h['spoken']}, in the Bronx. {h['injury']} injury crashes in five years, the most of New York's "
                      f"{cw.get('intersections')} priority intersections. {h['peds']} pedestrians hurt. In the federal "
                      f"government's own values, that harm costs {h['harm_m']:.1f} million dollars a year. The city's "
                      f"records show no safety work here since {h['last_project']}.", "card",
              "One intersection, five years",
              f"{h['name']}, Bronx: {h['injury']} injury crashes, {h['peds']} pedestrians hurt, "
              f"${h['harm_m']:.1f}M a year in harm (USDOT values). Last recorded safety work: {h['last_project']}."),
        Scene("map", f"NearMissLens is a junction safety copilot built on Meta's models. Every dot is a priority "
                     f"intersection. Red means many injury crashes, and nothing done: {cw.get('plan_gap')} of them.",
              "app", target="", caption="Junction Safety Copilot: every NYC priority intersection, from open city data"),
        Scene("brief", "Agents pull the police crash record, the city's designations and its past projects, then rank "
                       "federal Proven Safety Countermeasures by the crashes each would prevent and what that is worth. "
                       "A checker rejects any number that is not in the record.", "app", target=h["q"]["address"],
              q=h["q"], caption="Official record, ranked and cited fixes with their dollar value, a checked brief"),
        Scene("fix", f"Muse Image draws the top fix, pedestrian refuge islands, on the state's aerial photo. SAM 3.1 "
                     f"keeps every real car untouched and checks that the islands were drawn. They would prevent about "
                     f"{top['expected_crashes_avoided_per_year']} pedestrian injury crashes a year.", "image",
              target=str(SETTINGS.runs_dir / "briefs" / HERO / "fix.jpg"),
              caption="Muse Image + SAM 3.1: the fix on the real junction (AI illustration, not a design)"),
        Scene("measured", f"Do these fixes work? We checked the city's own record. At {lpi.get('sites', 0):,} "
                          f"intersections where New York added a leading pedestrian interval, pedestrian injury crashes "
                          f"fell {drop} percent, compared with intersections that got one later. A fake earlier date "
                          f"shows no drop. The national figure the copilot ranks with says {round(100 * (1 - cmf))}.",
              "card", "The city's own fixes, measured",
              f"Leading pedestrian intervals at {lpi.get('sites', 0):,} NYC intersections: pedestrian injury crashes "
              f"-{drop}% (95% interval {lo}-{hi}%). Placebo: no change. National CMF: -{round(100 * (1 - cmf))}%."),
        Scene("letter", "Then it drafts a letter to the people who can ask for the fix: the council member and the "
                        "community board, found from the city's district maps. Every number is checked, the sources "
                        "are attached, and the resident sends it.", "letter", target=h["q"]["address"], q=h["q"],
              caption="A checked letter to Council District and Community Board, drafted from the record"),
        Scene("seattle", "It is not wired to one city. For Seattle, a data agent searched public catalogs, mapped the "
                         "city's crash data, and fixed its own mapping after a validator rejected it twice.", "app",
              target="3rd Avenue & Pike Street, Seattle, WA",
              caption="A city it had never seen: data found, mapped and validated by an agent"),
        Scene("video", "Where video exists, SAM 3.1 tracks every road user in drone footage and measures near-misses "
                       "before crashes happen. On footage it had never seen, near-miss agreement rose from "
                       f"{pet0:.2f} to {pet1:.2f}.", "viewer",
              caption="SAM 3.1 near-miss measurement on drone video (FLUID dataset, CC BY 4.0)"),
        Scene("intake", f"Residents can report a near-miss. An agent checks the complaint against the evidence. On "
                        f"{spark.get('n')} test complaints it was right every time, at a fifth of a cent each.",
              "intake", target="Every day at this junction, scooters coming from the north side and turning right "
                               "nearly hit cars.", caption="Complaint checked against the measured evidence"),
        Scene("proof", "Every claim is measured, and we report what failed. Residents' near-miss reports did not "
                       "predict crashes better than crash history, and video review hurt our verifier.", "card",
              "Measured, including what failed",
              "Pre-registered benchmark on 14 drone flights, 3 junctions and 3 cities. Negative results reported."),
        Scene("open", "The agents also run on Meta's open weights: Muse Spark Open on Baseten, and Muse Glimmer on a "
                      "Modal GPU.", "card", "Meta models throughout",
              "SAM 3.1 · Muse Spark · Muse Wonder · Muse Image · Voice Transcribe · Spark Open · Glimmer"),
        Scene("end", "NearMissLens. Open source, built during the hackathon. It screens; engineers decide.", "card",
              "NearMissLens", "Open source, built during the hackathon. A screening tool: engineers decide."),
    ]


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
            wav = work / f"{k:02d}_{s.name}.wav"
            secs = narrate(s.narration, wav) + PAD_S
            if s.kind == "card":
                seg = demo.card(s.title, s.caption or s.target, work / f"card_{s.name}", work, secs)
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
