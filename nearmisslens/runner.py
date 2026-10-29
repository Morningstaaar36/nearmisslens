from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from . import audit, complaints, countermeasures, evaluate, fluid, pipeline, render, verifier, video, voice
from .cache import file_sha256
from .config import SETTINGS
from .cost import IMAGE_USD, SAM_IMAGE_USD, voice_usd
from .meta_client import MetaClient

VERIFY_USD = 0.002


def site_states(split: str, source: str, client: MetaClient | None = None):
    """Engine states for a split: FLUID reference trajectories, or SAM 3.1 tracks over the same frames."""
    site, limit_s = evaluate.SPLITS[split]
    c = fluid.clip(*site)
    info = video.probe(c.video)
    duration = info["frames"] / info["fps"]
    if limit_s:
        duration = min(duration, limit_s)
    frames = (1, int(round(duration * info["fps"])))
    if source == "reference":
        st = pipeline.reference_states(c, frames)
        return c, st[st["isReal"] == 1].reset_index(drop=True)
    from . import tracks
    points = pipeline.track_api(client or MetaClient(SETTINGS), c, 0.0, duration, evaluate.CONCEPTS,
                                SETTINGS.data_dir / "work" / split, pipeline.calibration_for(c))
    st = tracks.smooth_states(points, info["fps"])
    return c, st[st["frame"].between(*frames)].reset_index(drop=True)


def estimate_usd(n_findings: int, verify_n: int, illustrate: bool) -> float:
    per_render = IMAGE_USD + (len(render.ROAD_USERS) + 2) * SAM_IMAGE_USD
    return n_findings * (verify_n * VERIFY_USD + (per_render if illustrate else 0.0))


def verify_finding(client: MetaClient, c: fluid.Clip, states: pd.DataFrame, pixels: pd.DataFrame, finding: dict,
                   n: int, work: Path) -> dict:
    """Muse Spark review of the finding's n most severe conflicts from event-centred video and speed traces."""
    info = video.probe(c.video)
    fps = info["fps"]
    verdicts = []
    for k, e in enumerate(finding["examples"][:n]):
        mid = int(round(e["t"] * fps))
        ids = (e["id_1"], e["id_2"])
        st = states.assign(id=states["id"].astype(str))
        px = pixels.assign(id=pixels["id"].astype(str))
        clip = verifier.render_event_clip(c.video, work / f"event_{ids[0]}_{ids[1]}_{mid}.mp4".replace(":", "-"), px,
                                          ids[0], ids[1], mid, fps, info["width"], info["height"])
        trace = verifier.speed_trace_png(st, ids[0], ids[1], mid, fps)
        metric = f"{e['measure']} {e['value']:.1f} s, {e['type'].replace('_', '-')}, A={e['cls_1']}, B={e['cls_2']}"
        v = verifier.verify(client, clip, trace, metric, f"audit {c.stem} h{finding['rank']} e{k}",
                            clip_key=verifier.event_key(c.video, ids[0], ids[1], mid, fps))
        verdicts.append({**e, **v})
    return {"reviewed": len(verdicts), "real": sum(bool(v["real_conflict"]) for v in verdicts),
            "evasive": sum(v["evasive_action"] in ("brake", "swerve", "both") for v in verdicts), "verdicts": verdicts}


def illustrate_finding(client: MetaClient, c: fluid.Clip, cal, finding: dict, out: Path) -> dict | None:
    specs = {i["name"]: i.get("render") for i in countermeasures.psc_items()}
    chosen = next((m for m in finding["countermeasures"] if specs.get(m["psc"])), None)
    if chosen is None:
        return None
    info = video.probe(c.video)
    t = finding["examples"][0]["t"] if finding["examples"] else 0.0
    frame = video.frame_at(c.video, int(round(t * info["fps"])))
    return render.render_fix(client, frame, cal, (finding["x"], finding["y"]), finding["cell_m"] / 2, chosen["psc"],
                             specs[chosen["psc"]], out, f"hotspot{finding['rank']}_{c.stem}")


def run_audit(split: str, source: str, verify_n: int = 0, illustrate: bool = False, out_root: Path | None = None,
              client: MetaClient | None = None) -> Path:
    client = client or MetaClient(SETTINGS)
    c, states = site_states(split, source, client)
    signals = fluid.load_signals(c)
    facts = audit.audit(states, countermeasures.load_cmf(), signals=signals,
                        control="Signalized" if len(signals) else None,
                        right_turn_signalised=fluid.has_right_turn_control(signals))
    out = (out_root or SETTINGS.runs_dir / "audit") / f"{split}_{source}"
    usd = estimate_usd(len(facts["findings"]), verify_n, illustrate)
    if usd:
        client.meter.check(usd, f"audit {split}")
        print(f"model calls for {len(facts['findings'])} hotspots: up to ${usd:.3f} (cached calls are free)")
    cal = pipeline.calibration_for(c) if (verify_n or illustrate) else None
    pixels = verifier.pixel_tracks(states, cal) if verify_n else None
    for f in facts["findings"]:
        if verify_n:
            f["verification"] = verify_finding(client, c, states, pixels, f, verify_n, SETTINGS.data_dir / "work" / "audit")
        if illustrate:
            il = illustrate_finding(client, c, cal, f, out)
            if il:
                f["illustration"] = il
    label = {"reference": "FLUID reference trajectories (YOLOv8-OBB + SparseTrack)",
             "sam": "SAM 3.1 tiled video tracking (Meta Model API)"}[source]
    audit.write(facts, audit.memo(facts, f"{c.site} {c.stem}", label), out, audit.conflict_table(states))
    return out


def as_wav(audio: Path, work: Path) -> Path:
    """16 kHz mono 16-bit WAV copy of any audio file ffmpeg can read."""
    out = work / f"input_{file_sha256(audio)[:12]}.wav"
    if not out.exists():
        work.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
                        str(out)], check=True)
    return out


def run_voice(split: str, source: str, audio: Path | None = None, client: MetaClient | None = None) -> Path:
    """Match a recording to the audit's hotspots, or, without one, test the intake on synthetic complaints spoken by
    MMS-TTS: one per hotspot and a decoy that no hotspot shows."""
    run = SETTINGS.runs_dir / "audit" / f"{split}_{source}"
    if not (run / "facts.json").exists():
        raise FileNotFoundError(f"no audit at {run}; run: nml audit {split} --source {source}")
    facts = json.loads((run / "facts.json").read_text())
    client = client or MetaClient(SETTINGS)
    work = SETTINGS.data_dir / "work" / "voice"
    tests = [] if audio else complaints.synthesize(facts)
    wavs = [as_wav(Path(audio), work)] if audio else [complaints.speak(c["text"], c["lang"], work) for c in tests]
    usd = sum(voice_usd(video.wav_seconds(w) + 1) + 0.002 for w in wavs)
    client.meter.check(usd, f"voice {split}")
    print(f"model calls for {len(wavs)} recordings: up to ${usd:.4f} (cached calls are free)")
    results = []
    for k, w in enumerate(wavs):
        r = voice.intake(client, w, facts, f"{split} {k}")
        if tests:
            c = tests[k]
            want = complaints.expected(c, facts)
            r |= {"synthetic": True, "source": c["source"], "lang": complaints.LANGS[c["lang"]], "spoken_text": c["text"],
                  "expected": sorted(want), "correct": (r["match"]["rank"] in want) if want else r["match"]["rank"] is None,
                  "word_error_rate": round(voice.word_error_rate(c["text"], r["transcript"]), 3)}
        results.append(r)
    summary = {"recordings": len(results)}
    if tests:
        summary |= {"correct": sum(r["correct"] for r in results),
                    "match_accuracy": round(sum(r["correct"] for r in results) / len(results), 3),
                    "mean_word_error_rate": round(sum(r["word_error_rate"] for r in results) / len(results), 3)}
    out = run / ("voice.json" if not audio else f"voice_{Path(audio).stem}.json")
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=1, default=str))
    return out
