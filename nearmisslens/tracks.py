from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from .calibrate import Calibration
from .segments import Detection

CONCEPT_CLASS = {"car": "vehicle", "bus": "vehicle", "truck": "vehicle", "van": "vehicle", "tricycle": "vehicle",
                 "scooter": "two_wheeler", "motorcycle": "two_wheeler", "moped": "two_wheeler",
                 "bicycle": "two_wheeler", "pedestrian": "pedestrian"}


def detections_to_points(dets: list[Detection], cal: Calibration, fps: float, frame_offset: int = 0,
                         prefix: str = "") -> pd.DataFrame:
    rows = []
    for d in dets:
        cx, cy, theta = d.centre()
        c, s = np.cos(theta), np.sin(theta)
        ys, xs = np.nonzero(d.mask)
        if len(xs) >= 3:
            u = (xs + d.x1 - cx) * c + (ys + d.y1 - cy) * s
            v = -(xs + d.x1 - cx) * s + (ys + d.y1 - cy) * c
            half_l, half_w = (u.max() - u.min()) / 2, (v.max() - v.min()) / 2
        else:
            half_l, half_w = (d.x2 - d.x1) / 2, (d.y2 - d.y1) / 2
        pts = np.array([[cx, cy], [cx + half_l * c, cy + half_l * s], [cx - half_w * s, cy + half_w * c]])
        m = cal.to_metres(pts)
        rows.append({"id": f"{prefix}{d.concept}:{d.obj}", "frame": d.frame + frame_offset, "cls": CONCEPT_CLASS.get(d.concept, "other"),
                     "concept": d.concept, "px": cx, "py": cy, "x": m[0, 0], "y": m[0, 1],
                     "length": 2 * np.linalg.norm(m[1] - m[0]), "width": 2 * np.linalg.norm(m[2] - m[0]),
                     "axis": float(np.arctan2(m[1, 1] - m[0, 1], m[1, 0] - m[0, 0])), "score": d.score or 0.0})
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
