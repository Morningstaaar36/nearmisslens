"""End-to-end self-test on real FLUID data and cached Meta API responses.

Every number is recomputed from the data and the response cache; nothing is copied from earlier runs.
With NML_REPLAY=1 no API call is made, and a check whose cached responses are missing is reported as SKIP.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import calibrate, conflicts, fluid, match, movements, pipeline, tiling, tracks, verifier, video
from .cache import ReplayMiss
from .config import ROOT, SETTINGS
from .meta_client import MetaClient
from .runlog import log_metrics

SMOKE_START_S = 60.0
SMOKE_DURATION_S = 10.0
SMOKE_CONCEPTS = ("car", "scooter")


@dataclass
class Check:
    name: str
    status: str = "SKIP"
    detail: dict = field(default_factory=dict)
    criterion: str = ""


def _work() -> Path:
    return SETTINGS.data_dir / "work" / "selftest"


def check_data() -> Check:
    ch = Check("data", criterion="dev, test and held-out videos and reference trajectories present and readable")
    missing = []
    for site in (fluid.DEV, fluid.TEST, fluid.HELDOUT):
        c = fluid.clip(*site)
        for p in (c.video, c.traj_path, c.signal_path, c.base_map):
            if not p.exists():
                missing.append(str(p))
    if missing:
        ch.status, ch.detail = "FAIL", {"missing": missing}
        return ch
    info = video.probe(fluid.clip(*fluid.DEV).video)
    ch.status, ch.detail = "PASS", info
    return ch


def check_calibration(max_median_m: float = 0.6) -> Check:
    ch = Check("calibration", criterion=f"median reprojection error against FLUID pixel-metre pairs <= {max_median_m} m on each clip")
    errs = {}
    for site in (fluid.DEV, fluid.TEST, fluid.HELDOUT):
        c = fluid.clip(*site)
        cal = pipeline.calibration_for(c)
        px, m = fluid.pixel_to_metre_pairs(fluid.load_trajectories(c, real_only=True))
        e = calibrate.reprojection_error(cal, px, m)
        errs[f"{c.site}_{c.stem}"] = {k: round(v, 3) if isinstance(v, float) else v for k, v in e.items()}
        log_metrics("calibration", f"{c.site}_{c.stem}", {"class": "", "median_m": e["median_m"], "p90_m": e["p90_m"]})
    ch.detail = errs
    ch.status = "PASS" if all(v["median_m"] <= max_median_m for v in errs.values()) else "FAIL"
    return ch


def check_engine() -> Check:
    ch = Check("conflict_engine", criterion="engine finds TTC events and crossing PET encounters on the dev reference trajectories")
    c = fluid.clip(*fluid.DEV)
    raw = fluid.load_trajectories(c)
    st = conflicts.from_fluid(raw, pipeline.clip_fps(c))
    t = time.time()
    ev = conflicts.ttc_events(st)
    pet = conflicts.pet_events(st[st["frame"] <= int(60 * pipeline.clip_fps(c))])
    ch.detail = {"ttc_events": int(len(ev)), "ttc_by_type": ev["type"].value_counts().to_dict(),
                 "pet_pairs_first_minute": int(len(pet)), "pet_le_1.5s": int((pet["pet"] <= 1.5).sum()),
                 "seconds": round(time.time() - t, 1)}
    ch.status = "PASS" if len(ev) > 0 and len(pet) > 0 else "FAIL"
    return ch


def check_linking(min_idf1: float = 0.9, noise_m: float = 0.3, seed: int = 0) -> Check:
    ch = Check("window_linking", criterion=(f"reference tracks cut into {pipeline.SEGMENT_S:.0f} s windows with fresh ids "
                                            f"and {noise_m} m position noise are re-linked with vehicle IDF1 >= {min_idf1}"))
    c = fluid.clip(*fluid.DEV)
    fps = pipeline.clip_fps(c)
    seg = int(round(pipeline.SEGMENT_S * fps))
    ov = int(round(pipeline.OVERLAP_S * fps))
    ref = pipeline.reference_states(c, (1, 1200))
    ref = ref[ref["isReal"] == 1]
    rng = np.random.default_rng(seed)
    parts = []
    for k, start in enumerate(range(1, int(ref["frame"].max()) + 1, seg)):
        w = ref[ref["frame"].between(start, start + seg + ov - 1)].copy()
        w["id"] = [f"s{k}:{i}" for i in w["id"]]
        w["segment"] = k
        w[["x", "y"]] += rng.normal(0, noise_m, (len(w), 2))
        parts.append(w)
    linked = pipeline.link_segments(pd.concat(parts, ignore_index=True), ov)
    res = {}
    for cls in ("vehicle", "two_wheeler"):
        m = match.tracking_metrics(linked, ref, cls, fps=fps)
        res[cls] = {k: round(float(m[k]), 3) for k in ("recall", "idf1", "id_switches_per_min")}
    ch.detail = res
    ch.status = "PASS" if res["vehicle"]["idf1"] >= min_idf1 else "FAIL"
    return ch


def check_routes(min_accuracy: float = 0.9) -> Check:
    ch = Check("routes", criterion=(f"entry-exit arms derived from reference positions agree with FLUID route labels "
                                    f">= {min_accuracy} on each clip; signal state on entry reported for through and left-turn users"))
    res = {}
    for site in (fluid.DEV, fluid.TEST, fluid.HELDOUT):
        c = fluid.clip(*site)
        ref = pipeline.reference_states(c, (1, 10 ** 9))
        ref = ref[ref["isReal"] == 1]
        acc = movements.route_accuracy(ref, ref.groupby("id")["overall_direction"].first())
        r = movements.routes(ref)
        sig = fluid.load_signals(c)
        entry = {}
        for cls in ("vehicle", "two_wheeler"):
            sub = r[(r["cls"] == cls) & r["movement"].isin(["through", "left"])]
            states = pd.Series([movements.entry_signal(sig, x) for x in sub.itertuples()]).dropna()
            entry[cls] = {k: round(float(v), 3) for k, v in states.value_counts(normalize=True).items()}
        res[f"{c.site}_{c.stem}"] = {"tracks": acc["tracks"], "route_accuracy": round(acc["route_accuracy"], 3),
                                     "entry_signal_share": entry}
    ch.detail = res
    ch.status = "PASS" if all(v["route_accuracy"] >= min_accuracy for v in res.values()) else "FAIL"
    return ch


def check_audit() -> Check:
    ch = Check("audit", criterion="audit of the dev reference finds hotspots, each with countermeasures that cite CMF Clearinghouse "
                                  "ids present in the database and pass the site checks")
    from . import audit, countermeasures
    c = fluid.clip(*fluid.DEV)
    ref = pipeline.reference_states(c, (1, 10 ** 9))
    ref = ref[ref["isReal"] == 1]
    sig = fluid.load_signals(c)
    cmf = countermeasures.load_cmf()
    facts = audit.audit(ref, cmf, signals=sig, control="Signalized", right_turn_signalised=fluid.has_right_turn_control(sig))
    known = set(cmf["crfid"])
    cited = [m["crfid"] for f in facts["findings"] for m in f["countermeasures"]]
    ch.detail = {"conflicts": facts["conflicts"], "hotspots": [
        {"rate_per_1000": f["rate_per_1000"], "ci95": f["ci95"], "dominant": f"{f['dominant']['type']} {'-'.join(f['dominant']['pair'])}",
         "countermeasures": [m["psc"] for m in f["countermeasures"]]} for f in facts["findings"]]}
    ch.status = "PASS" if facts["findings"] and cited and all(i in known for i in cited) else "FAIL"
    return ch


def check_tracking(client: MetaClient, min_recall: float = 0.6, min_precision: float = 0.8,
                   max_rmse_m: float = 1.0) -> Check:
    ch = Check("tracking_smoke", criterion=(f"SAM 3.1 tiled tracking on dev {SMOKE_START_S:.0f}-{SMOKE_START_S + SMOKE_DURATION_S:.0f} s: "
                                            f"vehicle recall >= {min_recall}, precision >= {min_precision}, position RMSE <= {max_rmse_m} m"))
    c = fluid.clip(*fluid.DEV)
    fps = pipeline.clip_fps(c)
    info = video.probe(c.video)
    tiles = tiling.grid(info["width"], info["height"])
    try:
        raw = tiling.track_tiles(client, c.video, SMOKE_START_S, SMOKE_DURATION_S, list(SMOKE_CONCEPTS), _work(), tiles, "selftest")
    except ReplayMiss as e:
        ch.detail = {"reason": f"no cached response ({e}); run without NML_REPLAY to fetch (cost about ${tiling.estimate_usd(int(SMOKE_DURATION_S * fps), len(tiles), len(SMOKE_CONCEPTS)):.2f})"}
        return ch
    dets = tiling.merge_tiles(raw, tiles)
    cal = pipeline.calibration_for(c)
    first = int(round(SMOKE_START_S * fps)) + 1
    last = first + int(round(SMOKE_DURATION_S * fps)) - 1
    ours = tracks.smooth_states(tracks.detections_to_points(dets, cal, fps, frame_offset=first), fps)
    ref = pipeline.reference_states(c, (first, last))
    ref = ref[ref["isReal"] == 1]
    res = {}
    for cls in ("vehicle", "two_wheeler"):
        m = match.tracking_metrics(ours, ref, cls, fps=fps)
        log_metrics("tracking_smoke", "dev_smoke", m)
        res[cls] = {k: round(float(v), 3) if isinstance(v, (float, np.floating)) else v for k, v in m.items()}
    ch.detail = res
    v = res["vehicle"]
    rmse = v.get("position_rmse_m", float("inf"))
    ch.status = "PASS" if (v["recall"] >= min_recall and v["precision"] >= min_precision and rmse <= max_rmse_m) else "FAIL"
    return ch


def check_verifier(client: MetaClient) -> Check:
    ch = Check("verifier", criterion="Muse Spark returns schema-valid verdicts for the three lowest-TTC mixed-class dev reference events")
    c = fluid.clip(*fluid.DEV)
    fps = pipeline.clip_fps(c)
    info = video.probe(c.video)
    raw = fluid.load_trajectories(c)
    st = conflicts.from_fluid(raw, fps)
    ev = conflicts.ttc_events(st)
    cands = ev[ev["cls_1"] != ev["cls_2"]].sort_values("min_ttc").head(3)
    pix = raw.rename(columns={"cx": "px", "cy": "py"}).assign(box_l=raw["w"], box_w=raw["h"], box_angle=raw["r"])
    verdicts = []
    try:
        for k, (_, e) in enumerate(cands.iterrows()):
            mid = int(e["frame_min_ttc"])
            clip = verifier.render_event_clip(c.video, _work() / f"event_{e.id_1}_{e.id_2}_{mid}.mp4", pix,
                                              e["id_1"], e["id_2"], mid, fps, info["width"], info["height"])
            trace = verifier.speed_trace_png(st, e["id_1"], e["id_2"], mid, fps)
            v = verifier.verify(client, clip, trace, f"min TTC {e['min_ttc']:.1f} s, {e['type']}, A={e['cls_1']}, B={e['cls_2']}",
                                f"selftest-{k}", clip_key=verifier.event_key(c.video, e["id_1"], e["id_2"], mid, fps))
            verdicts.append(v)
    except ReplayMiss as err:
        ch.detail = {"reason": f"no cached response ({err}); run without NML_REPLAY to fetch (about $0.002)"}
        return ch
    required = set(verifier.VERDICT_SCHEMA["required"])
    ok = len(verdicts) == len(cands) and all(required <= set(v) for v in verdicts)
    ch.detail = {"n": len(verdicts), "real_conflict": [v["real_conflict"] for v in verdicts]}
    ch.status = "PASS" if ok and verdicts else "FAIL"
    return ch


def run(replay: bool = True) -> list[Check]:
    if replay:
        SETTINGS.replay = True
    client = MetaClient(SETTINGS)
    data = check_data()
    checks = [data]
    if data.status == "PASS":
        checks += [check_calibration(), check_engine(), check_linking(), check_routes(), check_audit(), check_tracking(client), check_verifier(client)]
    return checks


def report(checks: list[Check]) -> str:
    lines = ["# Self-test", "", f"Generated by `nml selftest` on {time.strftime('%Y-%m-%d %H:%M')}. Every value is recomputed by the code.", "",
             "| Check | Status | Criterion | Result |", "|---|---|---|---|"]
    for ch in checks:
        lines.append(f"| {ch.name} | {ch.status} | {ch.criterion} | `{json.dumps(ch.detail, default=str)}` |")
    return "\n".join(lines) + "\n"


def main(replay: bool = True, write: bool = True) -> int:
    checks = run(replay)
    text = report(checks)
    print(text)
    if write:
        (ROOT / "validation" / "SELFTEST.md").write_text(text)
    return 1 if any(ch.status == "FAIL" for ch in checks) else 0
