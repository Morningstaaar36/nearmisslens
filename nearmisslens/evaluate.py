from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import conflicts, fluid, match, movements, pipeline, tracks
from .config import SETTINGS
from .runlog import log_metrics

CLASSES = ("vehicle", "two_wheeler", "pedestrian")
RESULTS_DIR = Path(__file__).resolve().parent.parent / "validation" / "results"


def evaluate_tracks(points: pd.DataFrame, c: fluid.Clip, frames: tuple[int, int], label: str,
                    stitch: bool = False, kinematics: tracks.Kinematics | None = None
                    ) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    fps = pipeline.clip_fps(c)
    ours = tracks.states(tracks.stitch(points, fps) if stitch else points, fps, kinematics)
    ours = ours[ours["frame"].between(*frames)]
    ref = pipeline.reference_states(c, frames)
    ref_real = ref[ref["isReal"] == 1]
    rows = []
    for cls in CLASSES:
        if (ref_real["cls"] == cls).sum() == 0:
            continue
        m = match.tracking_metrics(ours, ref_real, cls, fps=pipeline.clip_fps(c))
        rows.append(log_metrics("tracking", label, m))
    return ours, ref, rows


def evaluate_conflicts(ours: pd.DataFrame, ref: pd.DataFrame, label: str) -> dict:
    ev_ours = conflicts.ttc_events(ours)
    ev_ref = conflicts.ttc_events(ref[conflicts.STATE_COLUMNS])
    pmap = match.id_map(ours, ref)
    overall = match.event_metrics(ev_ours, ev_ref, pmap)
    log_metrics("conflicts_ttc", label, {"class": "all", **overall})
    out = {"all": overall}
    for limit in conflicts.SEVERITY_TTC_S[:-1]:
        sev = f"ttc<={limit}"
        o = ev_ours[ev_ours["min_ttc"] <= limit]
        r = ev_ref[ev_ref["min_ttc"] <= limit]
        out[sev] = match.event_metrics(o, r, pmap)
        log_metrics("conflicts_ttc", label, {"class": sev, **out[sev]})
    for kind in ("rear_end", "crossing", "lane_change"):
        out[kind] = match.event_metrics(ev_ours[ev_ours["type"] == kind], ev_ref[ev_ref["type"] == kind], pmap)
        log_metrics("conflicts_ttc", label, {"class": kind, **out[kind]})
    pet_ours = conflicts.pet_events(ours)
    pet_ref = conflicts.pet_events(ref[conflicts.STATE_COLUMNS])
    for band in (1.5, 3.0):
        out[f"pet<={band}"] = match.pet_metrics(pet_ours, pet_ref, pmap, band)
        log_metrics("conflicts_pet", label, {"class": f"pet<={band}", **out[f"pet<={band}"]})
    return {"summary": out, "ours": ev_ours, "ref": ev_ref, "pet_ours": pet_ours, "pet_ref": pet_ref, "map": pmap}


def write_events(result: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    result["ours"].to_csv(out / "events_ours.csv", index=False)
    result["ref"].to_csv(out / "events_reference.csv", index=False)
    result["pet_ours"].to_csv(out / "pet_ours.csv", index=False)
    result["pet_ref"].to_csv(out / "pet_reference.csv", index=False)
    (out / "conflict_summary.json").write_text(json.dumps(result["summary"], indent=1, default=float))


SPLITS = {"dev": (fluid.DEV, None), "test": (fluid.TEST, 600.0), "heldout": (fluid.HELDOUT, None)}
CONCEPTS = ["car", "scooter"]


def run_split(name: str, client, work_root: Path, out_root: Path, stitch: bool = False) -> dict:
    """Track a pre-registered split with the tiled SAM 3.1 API, then score tracking and conflicts against the reference.
    stitch scores the same tracks after track stitching (PREREG change 9), written under <split>/stitched."""
    from . import video
    site, limit_s = SPLITS[name]
    c = fluid.clip(*site)
    info = video.probe(c.video)
    duration = info["frames"] / info["fps"]
    if limit_s:
        duration = min(duration, limit_s)
    cal = pipeline.calibration_for(c)
    points = pipeline.track_api(client, c, 0.0, duration, CONCEPTS, work_root / name, cal)
    frames = (1, int(round(duration * info["fps"])))
    label = f"{name} stitched" if stitch else name
    ours, ref, rows = evaluate_tracks(points, c, frames, label, stitch=stitch)
    res = evaluate_conflicts(ours, ref, label)
    dest = out_root / name / ("stitched" if stitch else "")
    write_events(res, dest)
    summary = {"split": name, "clip": f"{c.site}_{c.stem}", "frames": frames, "tracking": rows,
               "conflicts": res["summary"], "stitched": stitch}
    (dest / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return summary


def signal_agreement(split: str) -> dict:
    """Share of entries on green, yellow and red per class, from SAM 3.1 tracks and from the reference, on the same
    frames; written next to the split's results."""
    from collections import Counter
    from .runner import site_states
    out = {}
    for source in ("reference", "sam"):
        c, st = site_states(split, source)
        sig = fluid.load_signals(c)
        r = movements.routes(st)
        for cls, g in r[r["cls"] != "pedestrian"].groupby("cls"):
            states = [s for s in (movements.entry_signal(sig, x) for x in g.itertuples()) if s]
            n = Counter(states)
            out.setdefault(cls, {})[source] = {"entries": len(states),
                                               **{k: round(n[k] / len(states), 3) if states else None for k in "Gyr"}}
    dest = RESULTS_DIR / split
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "signal_entry.json").write_text(json.dumps(out, indent=1))
    return out


EXPERIMENT_WINDOW_S = (60.0, 60.0)
TWO_WHEELER_VARIANTS = [("scooter", (2, 2)), ("motorcycle", (2, 2)), ("motorbike", (2, 2)),
                        ("person riding a scooter", (2, 2)), ("scooter", (3, 3))]


def experiment_usd(variants=TWO_WHEELER_VARIANTS, window=EXPERIMENT_WINDOW_S) -> float:
    from .tiling import estimate_usd
    frames = int(window[1] * 10)
    return sum(estimate_usd(frames, cols * rows, 1) for _, (cols, rows) in variants)


def two_wheeler_experiment(client, variants=TWO_WHEELER_VARIANTS, window=EXPERIMENT_WINDOW_S) -> list[dict]:
    """Two-wheeler tracking on the development clip only, one SAM 3.1 concept and tile grid per variant, scored
    against the reference on the same frames (PREREG change 8)."""
    c = fluid.clip(*fluid.DEV)
    fps = pipeline.clip_fps(c)
    cal = pipeline.calibration_for(c)
    start, duration = window
    frames = (int(round(start * fps)) + 1, int(round((start + duration) * fps)))
    rows = []
    for concept, grid in variants:
        points = pipeline.track_api(client, c, start, duration, [concept], Path(SETTINGS.data_dir) / "work" / "experiment",
                                    cal, grid=grid)
        label = f"dev {concept} {grid[0]}x{grid[1]}"
        if points.empty:
            rows.append({"concept": concept, "grid": list(grid), "recall": 0.0, "precision": float("nan")})
            continue
        _, _, metrics = evaluate_tracks(points, c, frames, label)
        m = next((r for r in metrics if r["class"] == "two_wheeler"), {})
        rows.append({"concept": concept, "grid": list(grid), **{k: m.get(k) for k in
                     ("recall", "precision", "position_rmse_m", "idf1", "ref_points", "pred_points")}})
    dest = RESULTS_DIR / "dev"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "two_wheeler_experiment.json").write_text(json.dumps(rows, indent=1, default=float))
    return rows


def results_markdown(summaries: list[dict]) -> str:
    lines = ["# Results", "", "Generated by `nml evaluate`. Agreement with FLUID reference trajectories "
             "(a trained YOLOv8-OBB + SparseTrack pipeline), per `validation/PREREG.md`.", ""]
    for s in summaries:
        lines += [f"## {s['split']}: {s['clip']}, frames {s['frames'][0]}-{s['frames'][1]}", "",
                  "| class | recall | precision | position RMSE (m) | speed MAE (m/s) | IDF1 |", "|---|---|---|---|---|---|"]
        for r in s["tracking"]:
            f = lambda k: f"{r[k]:.3f}" if isinstance(r.get(k), (int, float)) else "n/a"
            lines.append(f"| {r['class']} | {f('recall')} | {f('precision')} | {f('position_rmse_m')} | {f('speed_mae_mps')} | {f('idf1')} |")
        lines += ["", "| conflict set | reference | ours | matched | precision | recall | F1 |", "|---|---|---|---|---|---|---|"]
        for k, v in s["conflicts"].items():
            g = lambda x: f"{v[x]:.3f}" if isinstance(v.get(x), float) and v[x] == v[x] else str(v.get(x, ""))
            lines.append(f"| {k} | {v['ref_events']} | {v['pred_events']} | {v['tp']} | {g('precision')} | {g('recall')} | {g('f1')} |")
        lines += _extra_results(s["split"])
    return "\n".join(lines)


def _rate(v) -> str:
    return f"{v:.3f}" if isinstance(v, float) and v == v else "n/a"


def _extra_results(split: str) -> list[str]:
    """Signal-entry agreement, the verifier test and B0, where they have been run for the split."""
    lines = [""]
    d = RESULTS_DIR / split
    if (d / "stitched" / "summary.json").exists() and (d / "summary.json").exists():
        reg, st = (json.loads((p / "summary.json").read_text()) for p in (d, d / "stitched"))
        lines += ["Same tracks after track stitching (PREREG change 9):", "",
                  "| measure | registered | stitched |", "|---|---|---|"]
        for r0, r1 in zip(reg["tracking"], st["tracking"]):
            if r0["class"] != "pedestrian":
                for k in ("recall", "idf1"):
                    lines.append(f"| {r0['class']} {k} | {_rate(r0.get(k))} | {_rate(r1.get(k))} |")
        for k in ("all", "pet<=1.5", "pet<=3.0"):
            lines.append(f"| conflicts {k} F1 | {_rate(reg['conflicts'][k]['f1'])} | {_rate(st['conflicts'][k]['f1'])} |")
        lines.append("")
    if (d / "kinematics" / "summary.json").exists() and (d / "summary.json").exists():
        reg, kin = (json.loads((p / "summary.json").read_text()) for p in (d, d / "kinematics"))
        lines += ["Same cached tracks, stitched, with Kalman/RTS kinematics chosen on dev (PREREG change 10, decided "
                  "after the test and held-out runs; its clean test is the fresh flights in BENCH.md):", "",
                  "| measure | registered F1 | Kalman/RTS F1 | Kalman/RTS precision | Kalman/RTS recall | Kalman/RTS F2 |",
                  "|---|---|---|---|---|---|"]
        for k in ("all", "ttc<=0.5", "ttc<=1.0", "rear_end", "crossing", "lane_change", "pet<=1.5", "pet<=3.0"):
            r0, r1 = reg["conflicts"][k], kin["conflicts"][k]
            lines.append(f"| {k} | {_rate(r0['f1'])} | {_rate(r1['f1'])} | {_rate(r1['precision'])} | "
                         f"{_rate(r1['recall'])} | {_rate(f2(r1))} |")
        lines.append("")
    if (d / "signal_entry.json").exists():
        se = json.loads((d / "signal_entry.json").read_text())
        lines += ["Signal state on entry, SAM 3.1 tracks against the reference (share of entries):", "",
                  "| class | source | entries | green | yellow | red |", "|---|---|---|---|---|---|"]
        for cls, by in se.items():
            for src, v in by.items():
                lines.append(f"| {cls} | {src} | {v['entries']} | {_rate(v['G'])} | {_rate(v['y'])} | {_rate(v['r'])} |")
        lines.append("")
    if (d / "verifier.json").exists():
        v = json.loads((d / "verifier.json").read_text())
        lines += [f"Muse Spark verifier on {v['candidates']} candidate conflicts: {v['rated_real']} rated real "
                  f"(artefact share {_rate(v['artefact_share'])}, ${v['usd_per_event']} per event).", "",
                  "| set | events | matched | precision | recall | F1 |", "|---|---|---|---|---|---|"]
        for name, key in (("all candidates", "before"), ("rated real by Muse Spark", "after"),
                          ("most severe, same recall", "severity_at_matched_recall")):
            r = v[key]
            lines.append(f"| {name} | {r['pred_events']} | {r['tp']} | {_rate(r['precision'])} | {_rate(r['recall'])} | {_rate(r['f1'])} |")
        lines.append("")
    if (d / "b0.json").exists():
        b = json.loads((d / "b0.json").read_text())
        lines += [f"B0, event level (same class pair, within {b['tolerance_s']} s) against {b['b0']['ref_events']} reference "
                  f"conflicts in {b['span_s']:.0f} s:", "", "| method | events | matched | precision | recall | F1 |",
                  "|---|---|---|---|---|---|"]
        for name, key in (("Muse Spark alone (B0)", "b0"), ("NearMissLens pipeline", "pipeline")):
            r = b[key]
            if "tp" in r:
                lines.append(f"| {name} | {r['pred_events']} | {r['tp']} | {_rate(r['precision'])} | {_rate(r['recall'])} | {_rate(r['f1'])} |")
        lines.append("")
    return lines


def write_results() -> str:
    """Regenerate validation/RESULTS.md from the stored split summaries and result files."""
    summaries = [json.loads((RESULTS_DIR / n / "summary.json").read_text()) for n in SPLITS
                 if (RESULTS_DIR / n / "summary.json").exists()]
    text = results_markdown(summaries)
    (RESULTS_DIR.parent / "RESULTS.md").write_text(text)
    return text


DEV_POINTS = "FIDRT_20250525_video_0_407_0_60_120_points.csv.gz"
KIN_GRID = {"accel_std": (1.0, 2.0, 3.0, 5.0, 8.0), "pos_std": (0.2, 0.35, 0.5), "gate": (9.2, 13.8, 25.0, float("inf")),
            "reset_after": (3, 6), "max_gap": (5, 15, 25)}


def velocity_error(st: pd.DataFrame, ref: pd.DataFrame, cls: str) -> dict:
    """Vector velocity error and size bias of our states against reference states at frame-matched points."""
    import numpy as np
    m = match.frame_matches(st, ref, cls)
    if m.empty:
        return {"points": 0}
    dv = np.hypot(st.loc[m["pi"], "vx"].to_numpy() - ref.loc[m["ri"], "vx"].to_numpy(),
                  st.loc[m["pi"], "vy"].to_numpy() - ref.loc[m["ri"], "vy"].to_numpy())
    return {"points": len(m), "mean_mps": float(np.mean(dv)), "median_mps": float(np.median(dv)),
            "share_over_1mps": float(np.mean(dv > 1.0)),
            "length_bias_m": float(np.mean(st.loc[m["pi"], "length"].to_numpy() - ref.loc[m["ri"], "length"].to_numpy())),
            "width_bias_m": float(np.mean(st.loc[m["pi"], "width"].to_numpy() - ref.loc[m["ri"], "width"].to_numpy()))}


_TUNE: dict = {}


def _tune_init(pts, ref, fps):
    _TUNE.update(pts=pts, ref=ref, fps=fps)


def _tune_one(combo) -> dict:
    a, p, g, r, mg = combo
    classes = ("vehicle", "two_wheeler")
    k = tracks.Kinematics(accel_std=tuple((cl, a) for cl in classes + ("pedestrian",)),
                          pos_std=tuple((cl, p) for cl in classes + ("pedestrian",)), gate=g, reset_after=r, max_gap=mg)
    st = tracks.kalman_states(_TUNE["pts"], _TUNE["fps"], k)
    return {"accel_std": a, "pos_std": p, "gate": g, "reset_after": r, "max_gap": mg,
            **{cl: velocity_error(st, _TUNE["ref"], cl) for cl in classes}}


def tune_kinematics(grid: dict = KIN_GRID, workers: int = 6) -> dict:
    """PREREG change 10: choose the Kalman/RTS parameters on the development clip only, by mean vector velocity error
    against the reference at matched points (never by conflict scores). Acceleration noise is chosen per class; the
    shared parameters minimise the point-weighted error of both classes. Size bias is then measured at the chosen
    parameters and corrected per class."""
    import itertools
    from dataclasses import replace
    c = fluid.clip(*fluid.DEV)
    fps = pipeline.clip_fps(c)
    pts = tracks.stitch(pd.read_csv(Path(SETTINGS.data_dir) / "work" / "dev" / DEV_POINTS), fps)
    ref = pipeline.reference_states(c, (int(pts["frame"].min()), int(pts["frame"].max())))
    ref = ref[ref["isReal"] == 1]
    classes = ("vehicle", "two_wheeler")
    from concurrent.futures import ProcessPoolExecutor
    combos = list(itertools.product(*grid.values()))
    with ProcessPoolExecutor(workers, initializer=_tune_init, initargs=(pts, ref, fps)) as ex:
        rows = list(ex.map(_tune_one, combos, chunksize=4))
    shared = {}
    for row in rows:
        shared.setdefault((row["pos_std"], row["gate"], row["reset_after"], row["max_gap"]), []).append(row)
    best = None
    for key, group in shared.items():
        pick = {cl: min(group, key=lambda r: r[cl]["mean_mps"]) for cl in classes}
        err = sum(pick[cl][cl]["mean_mps"] * pick[cl][cl]["points"] for cl in classes) / \
            sum(pick[cl][cl]["points"] for cl in classes)
        if best is None or err < best[0]:
            best = (err, key, {cl: pick[cl]["accel_std"] for cl in classes})
    _, (p, g, r, mg), acc = best
    k = tracks.Kinematics(accel_std=tuple(acc.items()) + (("pedestrian", acc["vehicle"]),),
                          pos_std=tuple((cl, p) for cl in classes + ("pedestrian",)), gate=g, reset_after=r, max_gap=mg)
    st = tracks.kalman_states(pts, fps, k)
    bias = {cl: velocity_error(st, ref, cl) for cl in classes}
    k = replace(k, size_bias_m=tuple((cl, (round(-bias[cl]["length_bias_m"], 2), round(-bias[cl]["width_bias_m"], 2)))
                                     for cl in classes) + (("pedestrian", (0.0, 0.0)),))
    baseline = tracks.smooth_states(pts, fps)
    out = {"chosen": {"accel_std": dict(k.accel_std), "pos_std": p, "gate": g, "reset_after": r, "max_gap": mg,
                      "size_bias_m": {cl: list(v) for cl, v in k.size_bias_m}},
           "dev_velocity_error": {"savgol_v0": {cl: velocity_error(baseline, ref, cl) for cl in classes},
                                  "kalman_v1": {cl: velocity_error(tracks.kalman_states(pts, fps, k), ref, cl)
                                                for cl in classes}},
           "grid": {kk: list(v) for kk, v in grid.items()}, "runs": rows}
    dest = RESULTS_DIR / "dev"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "kinematics_tuning.json").write_text(json.dumps(out, indent=1, default=float))
    return out


KIN_PATH = RESULTS_DIR / "dev" / "kinematics_tuning.json"


def chosen_kinematics() -> tracks.Kinematics:
    """The Kalman/RTS parameters chosen on the development clip (PREREG change 10)."""
    ch = json.loads(KIN_PATH.read_text())["chosen"]
    classes = ("vehicle", "two_wheeler", "pedestrian")
    acc = ch["accel_std"]
    return tracks.Kinematics(accel_std=tuple((c, acc.get(c, acc["vehicle"])) for c in classes),
                             pos_std=tuple((c, ch["pos_std"]) for c in classes), gate=ch["gate"],
                             reset_after=ch["reset_after"], max_gap=ch["max_gap"],
                             size_bias_m=tuple((c, tuple(ch["size_bias_m"].get(c, (0.0, 0.0)))) for c in classes))


def f2(m: dict) -> float:
    """Recall-weighted F2 = 5TP / (5TP + 4FN + FP), the USDOT Intersection Safety Challenge conflict score."""
    tp, fn, fp = m["tp"], m["ref_events"] - m["tp"], m["pred_events"] - m["tp"]
    return 5 * tp / (5 * tp + 4 * fn + fp) if (5 * tp + 4 * fn + fp) else float("nan")


def rescore_split(name: str) -> dict:
    """PREREG change 10: the registered split's cached SAM 3.1 tracks scored with stitching and the chosen Kalman/RTS
    kinematics (no new tracking), written under <split>/kinematics."""
    from .runner import site_states  # noqa: F401 (site paths)
    site, limit_s = SPLITS[name]
    c = fluid.clip(*site)
    from . import video
    info = video.probe(c.video)
    duration = info["frames"] / info["fps"]
    if limit_s:
        duration = min(duration, limit_s)
    points = pipeline.track_api(None, c, 0.0, duration, CONCEPTS, Path(SETTINGS.data_dir) / "work" / name,
                                pipeline.calibration_for(c), cached_only=True)
    frames = (1, int(round(duration * info["fps"])))
    label = f"{name} kinematics"
    ours, ref, rows = evaluate_tracks(points, c, frames, label, stitch=True, kinematics=chosen_kinematics())
    res = evaluate_conflicts(ours, ref, label)
    dest = RESULTS_DIR / name / "kinematics"
    write_events(res, dest)
    summary = {"split": name, "clip": f"{c.site}_{c.stem}", "frames": frames, "tracking": rows,
               "conflicts": res["summary"], "stitched": True, "kinematics": "kalman_rts"}
    (dest / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return summary
