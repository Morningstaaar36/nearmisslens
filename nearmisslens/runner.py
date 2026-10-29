from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

from . import audit, complaints, countermeasures, evaluate, fluid, pipeline, render, verifier, video, voice
from .cache import file_sha256
from .config import ROOT, SETTINGS
from .cost import IMAGE_USD, SAM_IMAGE_USD, voice_usd
from .meta_client import MetaClient

VERIFY_USD = 0.002
# Road-user classes whose signal state on entry is used as evidence. With SAM 3.1 tracks only vehicles agree with the
# reference on the registered clips (validation/results/*/signal_entry.json, PREREG change 7).
SIGNAL_CLASSES = {"reference": ("vehicle", "two_wheeler"), "sam": ("vehicle",)}


def site_states(split: str, source: str, client: MetaClient | None = None):
    """Engine states for a split: FLUID reference trajectories, or the SAM 3.1 tracks that nml evaluate produced over
    the same frames (never tracks here; raises FileNotFoundError when they are missing)."""
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
                                SETTINGS.data_dir / "work" / split, pipeline.calibration_for(c), cached_only=True)
    st = tracks.smooth_states(tracks.stitch(points, info["fps"]), info["fps"])
    return c, st[st["frame"].between(*frames)].reset_index(drop=True)


def estimate_usd(n_findings: int, verify_n: int, illustrate: bool) -> float:
    per_render = IMAGE_USD + (len(render.ROAD_USERS) + 2) * SAM_IMAGE_USD
    return n_findings * (verify_n * VERIFY_USD + (per_render if illustrate else 0.0))


def review_event(client: MetaClient, c: fluid.Clip, info: dict, states: pd.DataFrame, pixels: pd.DataFrame, e: dict,
                 work: Path, tag: str) -> dict:
    """Muse Spark verdict on one conflict (a conflict-table row) from its event-centred video and speed trace.
    states and pixels must carry string ids."""
    fps = info["fps"]
    mid = int(round(e["t"] * fps))
    ids = (str(e["id_1"]), str(e["id_2"]))
    pad = int(round(verifier.PAD_S * fps))
    pair = pixels[pixels["id"].isin(ids) & pixels["frame"].between(mid - pad, mid + pad)].sort_values(["id", "frame"])
    tracks_sha = hashlib.sha256(pair[["id", "frame", "px", "py"]].round(1).to_csv(index=False).encode()).hexdigest()[:12]
    name = f"event_{c.stem}_{ids[0]}_{ids[1]}_{mid}_{tracks_sha}.mp4".replace(":", "-")
    clip = verifier.render_event_clip(c.video, work / name, pixels, ids[0], ids[1], mid, fps, info["width"], info["height"])
    trace = verifier.speed_trace_png(states, ids[0], ids[1], mid, fps)
    metric = f"{e['measure']} {e['value']:.1f} s, {e['type'].replace('_', '-')}, A={e['cls_1']}, B={e['cls_2']}"
    key = f"{verifier.event_key(c.video, ids[0], ids[1], mid, fps)}|tracks={tracks_sha}"
    return {**verifier.verify(client, clip, trace, metric, tag, clip_key=key), "clip": str(clip)}


def verify_finding(client: MetaClient, c: fluid.Clip, states: pd.DataFrame, pixels: pd.DataFrame, finding: dict,
                   n: int, work: Path) -> dict:
    """Muse Spark review of the finding's n most severe conflicts from event-centred video and speed traces."""
    info = video.probe(c.video)
    st = states.assign(id=states["id"].astype(str))
    px = pixels.assign(id=pixels["id"].astype(str))
    verdicts = [{**e, **review_event(client, c, info, st, px, e, work, f"audit {c.stem} h{finding['rank']} e{k}")}
                for k, e in enumerate(finding["examples"][:n])]
    return {"reviewed": len(verdicts), "real": sum(bool(v["real_conflict"]) for v in verdicts),
            "evasive": sum(v["evasive_action"] in ("brake", "swerve", "both") for v in verdicts), "verdicts": verdicts}


def severity_at_recall(cand: pd.DataFrame, ref: pd.DataFrame, recall: float) -> dict:
    """The smallest set of most severe candidates (lowest PET or TTC) whose recall reaches the given recall: the
    no-model comparison for the verifier at matched recall."""
    from .baseline import score
    ranked = cand.sort_values("value").reset_index(drop=True)
    for k in range(len(ranked) + 1):
        s = score(ranked.head(k), ref)
        if s["recall"] == s["recall"] and s["recall"] >= recall - 1e-12:
            return {**s, "kept": k}
    return {**score(ranked, ref), "kept": len(ranked)}


def run_verifier(split: str, client: MetaClient | None = None) -> dict:
    """Pre-registered verifier test: Muse Spark reviews every candidate conflict the pipeline finds on SAM 3.1 tracks;
    precision and recall against the reference conflict table before and after dropping the events it judges not real."""
    from .baseline import score
    client = client or MetaClient(SETTINGS)
    c, ours = site_states(split, "sam", client)
    _, ref_states = site_states(split, "reference")
    cand = audit.conflict_table(ours)
    ref = audit.conflict_table(ref_states)
    usd = len(cand) * VERIFY_USD
    client.check_budget(usd, f"verifier {split}")
    print(f"verifier: {len(cand)} candidate conflicts, up to ${usd:.2f} (cached calls are free)")
    info = video.probe(c.video)
    st = ours.assign(id=ours["id"].astype(str))
    px = verifier.pixel_tracks(st, pipeline.calibration_for(c))
    work = SETTINGS.data_dir / "work" / f"verify_{split}"
    verdicts = [review_event(client, c, info, st, px, e, work, f"{split} event {k}")
                for k, e in enumerate(cand.to_dict("records"))]
    kept = cand[[bool(v["real_conflict"]) for v in verdicts]]
    after = score(kept, ref)
    out = {"split": split, "candidates": int(len(cand)), "judged_real": int(len(kept)),
           "artefact_share": round(1 - len(kept) / len(cand), 3) if len(cand) else None,
           "before": score(cand, ref), "after": after, "severity_at_matched_recall": severity_at_recall(cand, ref, after["recall"]),
           "usd_per_event": round(client.meter.spent_on(f"verify {split} event ") / len(cand), 5) if len(cand) else None}
    dest = ROOT / "validation" / "results" / split
    dest.mkdir(parents=True, exist_ok=True)
    cand.assign(**{k: [v[k] for v in verdicts] for k in verdicts[0]} if verdicts else {}).to_csv(dest / "verifier_events.csv", index=False)
    (dest / "verifier.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def illustrate_finding(client: MetaClient, c: fluid.Clip, cal, finding: dict, out: Path) -> dict | None:
    specs = {i["name"]: i.get("render") for i in countermeasures.psc_items()}
    chosen = next((m for m in finding["countermeasures"] if specs.get(m["psc"])), None)
    if chosen is None:
        return None
    info = video.probe(c.video)
    t = finding["examples"][0]["t"] if finding["examples"] else 0.0
    frame = video.frame_at(c.video, int(round(t * info["fps"])))
    return render.render_fix(client, frame, cal, (finding["x"], finding["y"]), finding["cell_m"], chosen["psc"],
                             specs[chosen["psc"]], out, f"hotspot{finding['rank']}_{c.stem}")


def run_audit(split: str, source: str, verify_n: int = 0, illustrate: bool = False, out_root: Path | None = None,
              client: MetaClient | None = None) -> Path:
    client = client or MetaClient(SETTINGS)
    c, states = site_states(split, source, client)
    signals = fluid.load_signals(c)
    facts = audit.audit(states, countermeasures.load_cmf(), signals=signals,
                        control="Signalized" if len(signals) else None,
                        right_turn_signalised=fluid.has_right_turn_control(signals),
                        signal_classes=SIGNAL_CLASSES[source])
    out = (out_root or SETTINGS.runs_dir / "audit") / f"{split}_{source}"
    usd = estimate_usd(len(facts["findings"]), verify_n, illustrate)
    if usd:
        client.check_budget(usd, f"audit {split}")
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
    facts_json = (run / "facts.json").read_text()
    facts = json.loads(facts_json)
    client = client or MetaClient(SETTINGS)
    work = SETTINGS.data_dir / "work" / "voice"
    tests = [] if audio else complaints.synthesize(facts)
    wavs = [as_wav(Path(audio), work)] if audio else [complaints.speak(c["text"], c["lang"], work) for c in tests]
    usd = sum(voice_usd(video.wav_seconds(w) + 1) + 0.002 for w in wavs)
    client.check_budget(usd, f"voice {split}")
    print(f"model calls for {len(wavs)} recordings: up to ${usd:.4f} (cached calls are free)")
    results = []
    for k, w in enumerate(wavs):
        r = voice.intake(client, w, facts, f"{split} {k}",
                         audio_key=complaints.audio_key(tests[k]["text"], tests[k]["lang"]) if tests else None)
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
    out.write_text(json.dumps({"facts_id": audit.facts_id(facts_json), "summary": summary, "results": results},
                              indent=1, default=str))
    return out
