from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.signal import savgol_filter

from .calibrate import Calibration
from .segments import Detection, decode_masks

CONCEPT_CLASS = {"car": "vehicle", "bus": "vehicle", "truck": "vehicle", "van": "vehicle", "tricycle": "vehicle",
                 "scooter": "two_wheeler", "motorcycle": "two_wheeler", "moped": "two_wheeler",
                 "bicycle": "two_wheeler", "motorbike": "two_wheeler", "person riding a scooter": "two_wheeler",
                 "pedestrian": "pedestrian"}


def _rect_px(d: Detection) -> tuple[float, float, float, float, float]:
    """Centre x, y, half-length, half-width (pixels) and axis angle of a decoded mask's minimum-area rectangle."""
    cx, cy, theta = d.centre()
    ys, xs = np.nonzero(d.mask)
    c, s = np.cos(theta), np.sin(theta)
    u = (xs + d.x1 - cx) * c + (ys + d.y1 - cy) * s
    v = -(xs + d.x1 - cx) * s + (ys + d.y1 - cy) * c
    return cx, cy, (u.max() - u.min() + 1) / 2, (v.max() - v.min() + 1) / 2, theta


def detections_to_points(dets: list[Detection], cal: Calibration, fps: float, frame_offset: int = 0,
                         prefix: str = "", samples_per_track: int = 4) -> pd.DataFrame:
    """One row per detection: box-centre position in metres, plus size and body axis from decoded mask samples."""
    by_track: dict[str, list[Detection]] = {}
    for d in dets:
        by_track.setdefault(f"{d.concept}:{d.obj}", []).append(d)
    sampled: dict[str, list[Detection]] = {}
    for key, ds in by_track.items():
        ds.sort(key=lambda d: d.frame)
        idx = np.unique(np.linspace(0, len(ds) - 1, min(samples_per_track, len(ds))).round().astype(int))
        sampled[key] = [ds[i] for i in idx if ds[i].mask is not None or ds[i].payload is not None]
    decode_masks([d for ds in sampled.values() for d in ds])
    rows = []
    for key, ds in by_track.items():
        shapes = []
        for d in sampled[key]:
            if d.mask is None or d.mask.sum() < 3:
                continue
            cx, cy, hl, hw, th = _rect_px(d)
            pts = np.array([[cx, cy], [cx + hl * np.cos(th), cy + hl * np.sin(th)],
                            [cx - hw * np.sin(th), cy + hw * np.cos(th)]])
            m = cal.to_metres(pts)
            shapes.append((d.frame, 2 * np.linalg.norm(m[1] - m[0]), 2 * np.linalg.norm(m[2] - m[0]),
                           float(np.arctan2(m[1, 1] - m[0, 1], m[1, 0] - m[0, 0])), 2 * hl, 2 * hw, th))
        if shapes:
            sf = np.array([s[0] for s in shapes])
            length = float(np.median([s[1] for s in shapes]))
            width = float(np.median([s[2] for s in shapes]))
            box_l = float(np.median([s[4] for s in shapes]))
            box_w = float(np.median([s[5] for s in shapes]))
        else:
            sf = np.array([], dtype=float)
            bw = float(np.median([d.x2 - d.x1 for d in ds]))
            bh = float(np.median([d.y2 - d.y1 for d in ds]))
            c0 = np.array([[(ds[0].x1 + ds[0].x2) / 2, (ds[0].y1 + ds[0].y2) / 2]])
            m = cal.to_metres(np.vstack([c0, c0 + [bw / 2, 0], c0 + [0, bh / 2]]))
            dims = sorted([2 * np.linalg.norm(m[1] - m[0]), 2 * np.linalg.norm(m[2] - m[0])], reverse=True)
            length, width, box_l, box_w = dims[0], dims[1], max(bw, bh), min(bw, bh)
        centres = np.array([[(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2] for d in ds])
        metres = cal.to_metres(centres)
        for d, (px, py), (x, y) in zip(ds, centres, metres):
            k = int(np.argmin(np.abs(sf - d.frame))) if len(sf) else -1
            rows.append({"id": f"{prefix}{key}", "frame": d.frame + frame_offset,
                         "cls": CONCEPT_CLASS.get(d.concept, "other"), "concept": d.concept, "px": px, "py": py,
                         "x": x, "y": y, "length": length, "width": width,
                         "axis": shapes[k][3] if k >= 0 else float("nan"), "box_l": box_l, "box_w": box_w,
                         "box_angle": shapes[k][6] if k >= 0 else 0.0, "score": d.score or 0.0})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["t"] = df["frame"] / fps
    return df


def stitch(points: pd.DataFrame, fps: float, max_gap_s: float = 1.0, max_dist_m: float = 2.0,
           edge_frames: int = 5) -> pd.DataFrame:
    """Join broken tracks: a track that ends is continued by a track of the same class that starts within max_gap_s,
    within max_dist_m of the position predicted from the first track's final velocity. Ends and starts are paired
    one to one by total distance (Hungarian), so chains of fragments join up."""
    if points.empty:
        return points
    ends, starts = [], []
    for tid, g in points.sort_values("frame").groupby("id"):
        tail, head = g.tail(edge_frames), g.head(edge_frames)
        v = _velocity(tail, fps)
        ends.append((tid, g["cls"].iloc[0], int(g["frame"].iloc[-1]), tail[["x", "y"]].to_numpy()[-1], v))
        starts.append((tid, g["cls"].iloc[0], int(g["frame"].iloc[0]), head[["x", "y"]].to_numpy()[0]))
    gap = max_gap_s * fps
    cost = np.full((len(ends), len(starts)), np.inf)
    for i, (ta, ca, fa, pa, va) in enumerate(ends):
        for j, (tb, cb, fb, pb) in enumerate(starts):
            if ta != tb and ca == cb and 0 < fb - fa <= gap:
                d = float(np.linalg.norm(pa + va * (fb - fa) / fps - pb))
                if d <= max_dist_m:
                    cost[i, j] = d
    ok = np.isfinite(cost)
    if not ok.any():
        return points
    rows, cols = linear_sum_assignment(np.where(ok, cost, 1e9))
    parent: dict[str, str] = {}

    def root(a: str) -> str:
        while parent.get(a, a) != a:
            a = parent[a]
        return a

    for i, j in zip(rows, cols):
        if ok[i, j] and root(ends[i][0]) != starts[j][0]:
            parent[starts[j][0]] = root(ends[i][0])
    out = points.copy()
    out["id"] = out["id"].map(lambda a: root(a))
    return out


def _velocity(g: pd.DataFrame, fps: float) -> np.ndarray:
    if len(g) < 2:
        return np.zeros(2)
    t = g["frame"].to_numpy(float) / fps
    return np.array([np.polyfit(t, g["x"].to_numpy(float), 1)[0], np.polyfit(t, g["y"].to_numpy(float), 1)[0]])


def _segments(frames: np.ndarray, max_gap: int) -> list[np.ndarray]:
    breaks = np.nonzero(np.diff(frames) > max_gap)[0]
    return np.split(np.arange(len(frames)), breaks + 1)


def smooth_states(points: pd.DataFrame, fps: float, window: int = 11, min_len: int = 5,
                  max_gap: int = 3) -> pd.DataFrame:
    """Savitzky-Golay positions and velocities from the raw positions, per gap-free segment of each track.

    Gaps up to max_gap frames are filled by linear interpolation; longer gaps split the track into segments.
    Yaw follows the motion direction when moving, otherwise the body axis.
    """
    cols = ["id", "frame", "t", "x", "y", "vx", "vy", "yaw", "length", "width", "cls"]
    out = []
    for tid, g in points.sort_values("frame").groupby("id"):
        g = g.drop_duplicates("frame")
        for seg in _segments(g["frame"].to_numpy(), max_gap):
            s = g.iloc[seg]
            if len(s) < min_len:
                continue
            full = np.arange(s["frame"].iloc[0], s["frame"].iloc[-1] + 1)
            x = np.interp(full, s["frame"], s["x"])
            y = np.interp(full, s["frame"], s["y"])
            axis = np.interp(full, s["frame"], np.unwrap(s["axis"].to_numpy()))
            n = len(full)
            w = min(window, n if n % 2 else n - 1)
            order = 2 if w > 3 else 1
            dt = 1.0 / fps
            seg_df = pd.DataFrame({"id": tid, "frame": full, "t": full / fps,
                                   "x": savgol_filter(x, w, order), "y": savgol_filter(y, w, order),
                                   "vx": savgol_filter(x, w, order, deriv=1, delta=dt),
                                   "vy": savgol_filter(y, w, order, deriv=1, delta=dt),
                                   "length": s["length"].median(), "width": s["width"].median(),
                                   "cls": s["cls"].iloc[0]})
            speed = np.hypot(seg_df["vx"], seg_df["vy"])
            motion = np.arctan2(seg_df["vy"], seg_df["vx"])
            body = np.where(np.cos(axis - motion) < 0, axis + np.pi, axis)
            seg_df["yaw"] = np.where(speed > 0.5, motion, body)
            out.append(seg_df[cols])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=cols)
