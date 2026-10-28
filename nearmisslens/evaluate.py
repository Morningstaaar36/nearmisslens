from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import conflicts, fluid, match, pipeline, tracks
from .runlog import log_metrics

CLASSES = ("vehicle", "two_wheeler", "pedestrian")


def evaluate_tracks(points: pd.DataFrame, c: fluid.Clip, frames: tuple[int, int], label: str) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    ours = tracks.smooth_states(points, pipeline.FPS)
    ours = ours[ours["frame"].between(*frames)]
    ref = pipeline.reference_states(c, frames)
    ref_real = ref[ref["isReal"] == 1]
    rows = []
    for cls in CLASSES:
        if (ref_real["cls"] == cls).sum() == 0:
            continue
        m = match.tracking_metrics(ours, ref_real, cls)
        rows.append(log_metrics("tracking", label, m))
    return ours, ref, rows


def evaluate_conflicts(ours: pd.DataFrame, ref: pd.DataFrame, label: str) -> dict:
    ev_ours = conflicts.ttc_events(ours)
    ev_ref = conflicts.ttc_events(ref[conflicts.STATE_COLUMNS])
    pmap = match.id_map(ours, ref)
    overall = match.event_metrics(ev_ours, ev_ref, pmap)
    log_metrics("conflicts_ttc", label, {"class": "all", **overall})
    out = {"all": overall}
    for sev in ("ttc<=0.5", "ttc<=1.0"):
        o = ev_ours[ev_ours["min_ttc"] <= float(sev[4:])]
        r = ev_ref[ev_ref["min_ttc"] <= float(sev[4:])]
        out[sev] = match.event_metrics(o, r, pmap)
        log_metrics("conflicts_ttc", label, {"class": sev, **out[sev]})
    for kind in ("rear_end", "crossing", "lane_change"):
        out[kind] = match.event_metrics(ev_ours[ev_ours["type"] == kind], ev_ref[ev_ref["type"] == kind], pmap)
        log_metrics("conflicts_ttc", label, {"class": kind, **out[kind]})
    return {"summary": out, "ours": ev_ours, "ref": ev_ref, "map": pmap}


def write_events(result: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    result["ours"].to_csv(out / "events_ours.csv", index=False)
    result["ref"].to_csv(out / "events_reference.csv", index=False)
    (out / "conflict_summary.json").write_text(json.dumps(result["summary"], indent=1, default=float))
