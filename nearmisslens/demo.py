"""Render the demo video from the product's own outputs: recordings of the replay viewer driven by a headless
browser, the SAM-outlined event clips, and title cards whose numbers are read from the run outputs. Nothing is
filmed, and a scene whose data does not exist yet is left out."""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT, SETTINGS
from .export import DOCS

W, H, FPS = 1920, 1080, 30
ZOOM = 1.25
LOAD_S = 2.5
INK, PAPER, MARKING = (29, 42, 51), (238, 241, 242), (232, 184, 30)
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/overpass/Overpass%5Bwght%5D.ttf"
FALLBACK_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CREDIT = "Footage and trajectories: FLUID dataset (Scientific Data, 2026), CC BY 4.0"


@dataclass
class Segment:
    path: Path
    seconds: float
    caption: str = ""
    skip: float = 0.0
    caption_top: bool = False


def font(size: int, work: Path) -> ImageFont.FreeTypeFont:
    path = work / "Overpass.ttf"
    if not path.exists():
        try:
            from .fetch import download
            download(FONT_URL, path)
        except Exception:
            return ImageFont.truetype(FALLBACK_FONT, size)
    f = ImageFont.truetype(str(path), size)
    try:
        f.set_variation_by_axes([800])
    except (OSError, AttributeError):
        pass
    return f


def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def card(title: str, body: str, out: Path, work: Path, seconds: float = 5.0, credit: str = CREDIT) -> Segment:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 18, W, H], fill=MARKING)
    ft, fb = font(92, work), font(46, work)
    y = 300
    for line in wrap(d, title, ft, W - 360):
        d.text((180, y), line, font=ft, fill=INK)
        y += 112
    y += 30
    for line in wrap(d, body, fb, W - 360):
        d.text((180, y), line, font=fb, fill=(91, 104, 113))
        y += 66
    if credit:
        d.text((180, H - 90), credit, font=font(28, work), fill=(91, 104, 113))
    png = out.with_suffix(".png")
    img.save(png)
    return Segment(png, seconds)


def _serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def record(base: str, name: str, steps, out_dir: Path) -> Path:
    """Record one viewer scene; steps(page) drives it."""
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=shutil.which("google-chrome") or shutil.which("chromium"),
                                    args=["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
        ctx = browser.new_context(viewport={"width": int(W / ZOOM), "height": int(H / ZOOM)}, record_video_dir=str(out_dir),
                                  record_video_size={"width": int(W / ZOOM), "height": int(H / ZOOM)})
        page = ctx.new_page()
        steps(page, base)
        video = page.video.path()
        ctx.close()
        browser.close()
    dest = out_dir / f"{name}.webm"
    Path(video).replace(dest)
    return dest


def _scenes(key: str, view: dict) -> list[tuple[str, str, object]]:
    """(name, caption, steps) for each viewer scene that has data."""
    facts = view["facts"]
    fs = facts["findings"]
    c = facts["conflicts"]
    out = []

    def map_steps(page, base):
        page.goto(f"{base}#audit={key}&view=2d")
        page.wait_for_timeout(2500)
        for f in fs:
            page.click(f'.picker button[data-r="{f["rank"]}"]')
            page.wait_for_timeout(2500)
        page.click(f'.picker button[data-r="{fs[0]["rank"]}"]')
        page.wait_for_timeout(1500)

    out.append(("map", f"{c['total']} conflicts in {facts['observed_s'] / 60:.0f} minutes, ranked into hotspots "
                       "by the lower bound of a 95% interval.", map_steps))
    if fs and fs[0].get("replays"):
        def replay_steps(page, base):
            page.goto(f"{base}#audit={key}&hotspot={fs[0]['rank']}&view=3d")
            page.wait_for_timeout(3000)
            page.click("#play")
            page.wait_for_timeout(4000)
            box = page.locator("#three").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] / 2 + 220, box["y"] + box["height"] / 2, steps=90)
            page.mouse.up()
            page.wait_for_timeout(5000)
        r = fs[0]["replays"][0]
        out.append(("replay", f"3D replay from measured tracks: {r['measure']} {r['value']:.1f} s between a "
                              f"{r['cls_1'].replace('_', '-')} and a {r['cls_2'].replace('_', '-')}.", replay_steps))
    illustrated = next((f for f in fs if (f.get("illustration") or {}).get("image")), None)
    if illustrated:
        il = illustrated["illustration"]
        m = next((m for m in illustrated["countermeasures"] if m["psc"] == il["countermeasure"]), None)
        cite = f" (CMF {m['crfid']}: {m['crf_pct']:.0f}% fewer {m['crash_type'].lower()} crashes)" if m else ""
        out.append(("fix", f"Muse Image illustrates {il['countermeasure']}{cite}. SAM 3.1 checks the edit: "
                           f"{'found' if il['check_passed'] else 'not found'}.", DOCS / "data" / il["image"]))
    for name, section, caption in (
            ("panel", "#panel-sec", _panel_caption(view.get("panel"))),
            ("voice", "#voice-sec", _voice_caption(view.get("voice"))),
            ("signals", "#signal-sec", "Signal state when each road user entered, from tracks and the signal log.")):
        if not caption:
            continue

        def section_steps(page, base, section=section):
            page.goto(f"{base}#audit={key}&view=2d")
            page.wait_for_timeout(1500)
            page.locator(section).scroll_into_view_if_needed()
            page.evaluate(f"document.querySelector('{section}').scrollIntoView({{block: 'start'}})")
            page.wait_for_timeout(7000)
        out.append((name, caption, section_steps))
    return out


def _panel_caption(p: dict | None) -> str:
    if not p or p.get("status") != "complete":
        return ""
    rejected = sum(not d["accept"] for d in p["decisions"])
    checker = (f"the grounding checker caught {p['caught']} unsupported claim{'s' if p['caught'] != 1 else ''}"
               if p["caught"] else "every claim passed the grounding checker")
    return (f"Proposer and Skeptic (Muse Spark) argue, the Arbiter (Muse Wonder) decides: {rejected} of "
            f"{len(p['decisions'])} recommendations rejected on the evidence; {checker}.")


def _voice_caption(v: dict | None) -> str:
    if not v or "match_accuracy" not in v["summary"]:
        return ""
    s = v["summary"]
    return (f"Spoken complaints (Muse Voice Transcribe) matched to measured hotspots: {s['correct']} of "
            f"{s['recordings']} synthetic test complaints correct.")


def reviewed_clip(view: dict) -> Segment | None:
    """The event clip of the first conflict Muse Spark reviewed in this audit, captioned with its verdict."""
    for f in view["facts"]["findings"]:
        for v in (f.get("verification") or {}).get("verdicts", []):
            path = Path(v.get("clip") or "")
            if v.get("clip") and path.exists():
                action = {"brake": "braking", "swerve": "swerving", "both": "braking and swerving"}.get(v["evasive_action"])
                verdict = ("rated a real conflict" + (f", with {action}" if action else "")) if v["real_conflict"] \
                    else "rated not a real conflict"
                return Segment(path, 8.0, f"{v['measure']} {v['value']:.1f} s between a {v['cls_1'].replace('_', '-')} "
                                          f"and a {v['cls_2'].replace('_', '-')}; Muse Spark watched the clip: {verdict}.")
    return None


def score_lines() -> list[str]:
    """Headline numbers from the registered results, where they exist."""
    lines = []
    res = ROOT / "validation" / "results"
    for split, label in (("test", "Test clip"), ("heldout", "Held-out intersection")):
        p = res / split / "summary.json"
        if p.exists():
            s = json.loads(p.read_text())
            v = next((r for r in s["tracking"] if r["class"] == "vehicle"), None)
            if v:
                lines.append(f"{label}: vehicles tracked with recall {v['recall']:.2f}, precision {v['precision']:.2f}, "
                             f"position error {v['position_rmse_m']:.2f} m.")
    b0 = res / "test" / "b0.json"
    if b0.exists():
        b = json.loads(b0.read_text())
        if "f1" in b.get("pipeline", {}):
            lines.append(f"Near-misses found, F1 against the reference: pipeline {b['pipeline']['f1']:.2f}, "
                         f"Muse Spark watching the video alone {b['b0']['f1']:.2f}.")
    vf = res / "test" / "verifier.json"
    if vf.exists():
        v = json.loads(vf.read_text())
        lines.append(f"Muse Spark video review: precision {v['before']['precision']:.2f} to {v['after']['precision']:.2f}.")
    return lines


def _to_clip(seg: Segment, out: Path, work: Path) -> Path:
    """1920x1080 at FPS, with the caption burned in as a bar at the bottom."""
    vf = [f"scale={W}:{H}:force_original_aspect_ratio=decrease", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x1d2a33",
          f"fps={FPS}", "format=yuv420p"]
    if seg.caption:
        txt = work / f"{out.stem}.txt"
        f = font(40, work)
        txt.write_text("\n".join(wrap(ImageDraw.Draw(Image.new("RGB", (1, 1))), seg.caption, f, W - 240)))
        vf.insert(2, f"drawtext=fontfile={f.path}:textfile={txt}:expansion=none:fontsize=40:line_spacing=12:"
                     f"fontcolor=white:x=(w-tw)/2:y={'50' if seg.caption_top else 'h-th-70'}:box=1:boxcolor=0x1d2a33@0.82:boxborderw=22")
    still = seg.path.suffix in (".png", ".jpg")
    cmd = ["ffmpeg", "-v", "error", "-y"] + (["-loop", "1", "-t", f"{seg.seconds}"] if still else []) + \
          (["-ss", f"{seg.skip}"] if seg.skip else []) + ["-i", str(seg.path)] + ([] if still else ["-t", f"{seg.seconds}"]) + \
          ["-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(out)]
    subprocess.run(cmd, check=True)
    return out


def render(key: str | None = None, out: Path | None = None) -> Path:
    index = json.loads((DOCS / "data" / "index.json").read_text())
    keys = [a["key"] for a in index["audits"]]
    key = key or next((k for k in ("heldout_sam", "test_sam", "heldout_reference", "dev_reference") if k in keys), keys[0])
    view = json.loads((DOCS / "data" / f"{key}.json").read_text())
    work = SETTINGS.data_dir / "work" / "demo"
    work.mkdir(parents=True, exist_ok=True)
    segs = [card("NearMissLens", "Near-misses happen long before crashes, and almost none are ever recorded. "
                                 "This finds them in ordinary traffic video and proposes cited fixes.", work / "c0", work)]
    ev = reviewed_clip(view)
    if ev:
        segs.append(ev)
    srv, base = _serve(DOCS)
    try:
        for name, caption, steps in _scenes(key, view):
            if isinstance(steps, Path):
                segs.append(Segment(steps, 8.0, caption, caption_top=True))
                continue
            webm = record(base, name, steps, work / "rec")
            segs.append(Segment(webm, float(_duration(webm)) - LOAD_S, caption, skip=LOAD_S))
    finally:
        srv.shutdown()
    lines = score_lines()
    if lines:
        segs.append(card("Checked against reference trajectories", " ".join(lines), work / "c_score", work, 9.0))
    segs.append(card("Open source, built during the hackathon",
                     "A screening tool built on surrogate safety measures, not a crash predictor. A qualified traffic "
                     "engineer must review any design.", work / "c_end", work))
    parts = [_to_clip(s, work / f"part{k:02d}.mp4", work) for k, s in enumerate(segs)]
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    out = out or SETTINGS.runs_dir / "demo" / "nearmisslens_demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
                   check=True)
    print(f"{out}: {_duration(out):.1f} s from {len(segs)} segments ({key})")
    return out


def _duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                        str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)
