from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from . import calibrate, conflicts, fluid, tiling, tracks, video
from .meta_client import MetaClient

FPS = 10.0
SEGMENT_S = 60.0
OVERLAP_S = 1.0


def link_segments(points: pd.DataFrame, overlap_frames: int, radius_m: float = 1.5) -> pd.DataFrame:
    """Join track ids across consecutive segments by matching positions in the overlapping frames."""
    if points.empty:
        return points
    points = points.copy()
    parent: dict[str, str] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            a = parent[a]
        return a

    segs = sorted(points["segment"].unique())
    for s0, s1 in zip(segs[:-1], segs[1:]):
        a = points[points["segment"] == s0]
        b = points[points["segment"] == s1]
        shared = sorted(set(a["frame"]) & set(b["frame"]))[:overlap_frames]
        votes: dict[tuple[str, str], int] = {}
        for f in shared:
            pa, pb = a[a["frame"] == f], b[b["frame"] == f]
            for cls in set(pa["cls"]) & set(pb["cls"]):
                xa = pa[pa["cls"] == cls]
                xb = pb[pb["cls"] == cls]
                D = np.linalg.norm(xa[["x", "y"]].to_numpy()[:, None] - xb[["x", "y"]].to_numpy()[None], axis=2)
                i, j = linear_sum_assignment(D)
                for p, q in zip(i[D[i, j] < radius_m], j[D[i, j] < radius_m]):
                    k = (xa["id"].iloc[p], xb["id"].iloc[q])
                    votes[k] = votes.get(k, 0) + 1
        for (ida, idb), n in votes.items():
            if n >= max(2, len(shared) // 3):
                parent[find(idb)] = find(ida)
    points["id"] = points["id"].map(find)
    later = points.duplicated(["id", "frame"], keep="first")
    return points[~later].reset_index(drop=True)


def track_api(client: MetaClient, c: fluid.Clip, start_s: float, duration_s: float, concepts: list[str],
              work: Path, cal: calibrate.Calibration) -> pd.DataFrame:
    out = work / f"{c.site}_{c.stem}_{start_s:.0f}_{duration_s:.0f}_points.csv.gz"
    if out.exists():
        return pd.read_csv(out)
    info = video.probe(c.video)
    tiles = tiling.grid(info["width"], info["height"])
    starts = list(np.arange(start_s, start_s + duration_s - 1e-6, SEGMENT_S))

    def segment(k_t):
        k, t = k_t
        seg_len = min(SEGMENT_S + OVERLAP_S, start_s + duration_s - t)
        raw = tiling.track_tiles(client, c.video, float(t), seg_len, concepts, work, tiles, f"{c.stem}@{t:.0f}")
        dets = tiling.merge_tiles(raw, tiles)
        pts = tracks.detections_to_points(dets, cal, FPS, frame_offset=int(round(t * FPS)) + 1, prefix=f"s{k}:")
        if not pts.empty:
            pts["segment"] = k
        return pts

    with ThreadPoolExecutor(3) as ex:
        parts = [p for p in ex.map(segment, enumerate(starts)) if not p.empty]
    points = link_segments(pd.concat(parts, ignore_index=True), int(OVERLAP_S * FPS)) if parts else pd.DataFrame()
    points.to_csv(out, index=False)
    return points


def reference_states(c: fluid.Clip, frames: tuple[int, int]) -> pd.DataFrame:
    raw = fluid.load_trajectories(c)
    raw = raw[raw["frame"].between(*frames)]
    st = conflicts.from_fluid(raw)
    return st.merge(raw[["id", "frame", "speed", "isReal", "cx", "cy", "w", "h", "r", "overall_direction"]],
                    on=["id", "frame"])


def calibration_for(c: fluid.Clip) -> calibrate.Calibration:
    return calibrate.calibrate(video.frame_at(c.video, 100), c.base_map)
