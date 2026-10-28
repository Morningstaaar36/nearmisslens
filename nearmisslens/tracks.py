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


def smooth_states(points: pd.DataFrame, fps: float, window: int = 11, min_len: int = 5) -> pd.DataFrame:
    """Per-track Savitzky-Golay smoothing of positions; velocity from its derivative; yaw from motion or body axis."""
    out = []
    for tid, g in points.sort_values("frame").groupby("id"):
        if len(g) < min_len:
            continue
        g = g.drop_duplicates("frame").copy()
        n = len(g)
        w = min(window, n if n % 2 else n - 1)
        order = 2 if w > 3 else 1
        dt = 1.0 / fps
        g["x"] = savgol_filter(g["x"], w, order)
        g["y"] = savgol_filter(g["y"], w, order)
        g["vx"] = savgol_filter(g["x"], w, order, deriv=1, delta=dt)
        g["vy"] = savgol_filter(g["y"], w, order, deriv=1, delta=dt)
        speed = np.hypot(g["vx"], g["vy"])
        motion = np.arctan2(g["vy"], g["vx"])
        axis = g["axis"].to_numpy()
        flip = np.cos(axis - motion) < 0
        body = np.where(flip, axis + np.pi, axis)
        g["yaw"] = np.where(speed > 0.5, motion, body)
        g["length"] = g["length"].median()
        g["width"] = g["width"].median()
        out.append(g)
    cols = ["id", "frame", "t", "x", "y", "vx", "vy", "yaw", "length", "width", "cls"]
    return pd.concat(out, ignore_index=True)[cols] if out else pd.DataFrame(columns=cols)
