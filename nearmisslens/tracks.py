from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from .calibrate import Calibration
from .segments import Detection, decode_masks

CONCEPT_CLASS = {"car": "vehicle", "bus": "vehicle", "truck": "vehicle", "van": "vehicle", "tricycle": "vehicle",
                 "scooter": "two_wheeler", "motorcycle": "two_wheeler", "moped": "two_wheeler",
                 "bicycle": "two_wheeler", "pedestrian": "pedestrian"}


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
            length = width = box_l = box_w = float("nan")
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
