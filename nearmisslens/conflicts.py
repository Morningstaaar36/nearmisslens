from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

TTC_MAX_S = 1.5
PET_MAX_S = 5.0
SEVERITY_TTC_S = (0.5, 1.0, 1.5)
HORIZON_S = 3.0
STEP_S = 0.1
PAIR_RADIUS_M = 30.0
GRID_M = 0.5
MIN_CLOSING_MPS = 1.0
MIN_MOVING_MPS = 0.5

STATE_COLUMNS = ["id", "frame", "t", "x", "y", "vx", "vy", "yaw", "length", "width", "cls"]
EVENT_COLUMNS = ["id_1", "id_2", "cls_1", "cls_2", "frame_start", "frame_end", "frame_min_ttc", "t_min_ttc",
                 "min_ttc", "angle", "type", "severity"]


@dataclass(frozen=True)
class Thresholds:
    ttc_s: float = TTC_MAX_S
    pet_s: float = PET_MAX_S


def _corners(x, y, yaw, length, width):
    c, s = np.cos(yaw), np.sin(yaw)
    hl, hw = length / 2, width / 2
    dx = np.stack([hl * c - hw * s, hl * c + hw * s, -hl * c + hw * s, -hl * c - hw * s], -1)
    dy = np.stack([hl * s + hw * c, hl * s - hw * c, -hl * s - hw * c, -hl * s + hw * c], -1)
    return np.stack([x[..., None] + dx, y[..., None] + dy], -1)


def _overlap(a, b):
    """Separating-axis test for batches of rectangles a, b with shape (..., 4, 2)."""
    hit = np.ones(a.shape[:-2], dtype=bool)
    for poly in (a, b):
        for k in range(2):
            edge = poly[..., k + 1, :] - poly[..., k, :]
            axis = np.stack([-edge[..., 1], edge[..., 0]], -1)
            pa = np.einsum("...ij,...j->...i", a, axis)
            pb = np.einsum("...ij,...j->...i", b, axis)
            hit &= (pa.max(-1) >= pb.min(-1)) & (pb.max(-1) >= pa.min(-1))
    return hit


def ttc_batch(s1: np.ndarray, s2: np.ndarray, horizon: float = HORIZON_S, step: float = STEP_S) -> np.ndarray:
    """Constant-velocity time to collision of oriented rectangles; inf when no collision within the horizon.

    s1, s2: arrays (n, 7) of x, y, vx, vy, yaw, length, width.
    """
    ts = np.arange(0.0, horizon + 1e-9, step)
    out = np.full(len(s1), np.inf)
    if len(s1) == 0:
        return out
    pending = np.ones(len(s1), dtype=bool)
    for t in ts:
        idx = np.nonzero(pending)[0]
        if len(idx) == 0:
            break
        a, b = s1[idx], s2[idx]
        ca = _corners(a[:, 0] + a[:, 2] * t, a[:, 1] + a[:, 3] * t, a[:, 4], a[:, 5], a[:, 6])
        cb = _corners(b[:, 0] + b[:, 2] * t, b[:, 1] + b[:, 3] * t, b[:, 4], b[:, 5], b[:, 6])
        hit = _overlap(ca, cb)
        out[idx[hit]] = t
        pending[idx[hit]] = False
    return out


def conflict_angle(v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
    a = np.arctan2(v1[:, 1], v1[:, 0]) - np.arctan2(v2[:, 1], v2[:, 0])
    return np.degrees(np.abs((a + np.pi) % (2 * np.pi) - np.pi))


def conflict_type(angle_deg: np.ndarray) -> np.ndarray:
    return np.where(angle_deg < 30, "rear_end", np.where(angle_deg > 85, "crossing", "lane_change"))


def pair_states(states: pd.DataFrame, radius: float = PAIR_RADIUS_M) -> pd.DataFrame:
    rows = []
    for frame, g in states.groupby("frame", sort=True):
        if len(g) < 2:
            continue
        xy = g[["x", "y"]].to_numpy()
        pairs = cKDTree(xy).query_pairs(radius, output_type="ndarray")
        if len(pairs) == 0:
            continue
        a = g.iloc[pairs[:, 0]].reset_index(drop=True)
        b = g.iloc[pairs[:, 1]].reset_index(drop=True)
        swap = a["id"].to_numpy() > b["id"].to_numpy()
        a2, b2 = a.copy(), b.copy()
        a2[swap], b2[swap] = b[swap].to_numpy(), a[swap].to_numpy()
        rows.append(pd.concat([a2.add_suffix("_1"), b2.add_suffix("_2")], axis=1))
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def ttc_frames(states: pd.DataFrame) -> pd.DataFrame:
    """Per pair and frame: TTC, closing speed and angle, with the artefact filter applied."""
    p = pair_states(states.dropna(subset=["x", "y", "vx", "vy", "yaw", "length", "width"]))
    if p.empty:
        return p
    p["frame"] = p["frame_1"]
    for n in ("1", "2"):
        p[f"speed_{n}"] = np.hypot(p[f"vx_{n}"], p[f"vy_{n}"])
    dx, dy = p["x_2"] - p["x_1"], p["y_2"] - p["y_1"]
    dist = np.hypot(dx, dy).clip(lower=1e-6)
    closing = -((p["vx_2"] - p["vx_1"]) * dx + (p["vy_2"] - p["vy_1"]) * dy) / dist
    p["closing_mps"] = closing
    keep = (closing > MIN_CLOSING_MPS) & (p["speed_1"] > MIN_MOVING_MPS) & (p["speed_2"] > MIN_MOVING_MPS)
    keep &= dist / closing.clip(lower=1e-6) < HORIZON_S + 2.0
    p = p[keep].reset_index(drop=True)
    if p.empty:
        return p
    cols = ["x", "y", "vx", "vy", "yaw", "length", "width"]
    s1 = p[[f"{c}_1" for c in cols]].to_numpy(float)
    s2 = p[[f"{c}_2" for c in cols]].to_numpy(float)
    p["ttc"] = ttc_batch(s1, s2)
    p["angle"] = conflict_angle(p[["vx_1", "vy_1"]].to_numpy(), p[["vx_2", "vy_2"]].to_numpy())
    p = p[np.isfinite(p["ttc"])]
    return p[p["ttc"] > 0].reset_index(drop=True)


def ttc_events(states: pd.DataFrame, th: Thresholds = Thresholds(), gap_frames: int = 5) -> pd.DataFrame:
    """Maximal intervals per pair with TTC at or below the threshold."""
    f = ttc_frames(states)
    if not f.empty:
        f = f[f["ttc"] <= th.ttc_s].sort_values(["id_1", "id_2", "frame"])
    if f.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    events = []
    for (i1, i2), g in f.groupby(["id_1", "id_2"]):
        frames = g["frame"].to_numpy()
        breaks = np.nonzero(np.diff(frames) > gap_frames)[0]
        for seg in np.split(np.arange(len(g)), breaks + 1):
            e = g.iloc[seg]
            k = e["ttc"].to_numpy().argmin()
            events.append({"id_1": i1, "id_2": i2, "cls_1": e["cls_1"].iloc[0], "cls_2": e["cls_2"].iloc[0],
                           "frame_start": int(e["frame"].min()), "frame_end": int(e["frame"].max()),
                           "frame_min_ttc": int(e["frame"].iloc[k]), "t_min_ttc": float(e["t_1"].iloc[k]), "min_ttc": float(e["ttc"].iloc[k]),
                           "angle": float(e["angle"].iloc[k])})
    ev = pd.DataFrame(events)
    ev["type"] = conflict_type(ev["angle"].to_numpy())
    ev["severity"] = np.select([ev["min_ttc"] <= s for s in SEVERITY_TTC_S], ["ttc<=0.5", "ttc<=1.0", "ttc<=1.5"],
                               default="")
    return ev


MIN_CROSSING_DEG = 30.0


def footprint_cells(x: np.ndarray, y: np.ndarray, yaw: np.ndarray, length: np.ndarray, width: np.ndarray,
                    cell: float, chunk: int = 20000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grid cells whose centres lie inside each oriented rectangle; returns (row, i, j). Every row gets at least its centre cell."""
    half = np.sqrt((length / 2) ** 2 + (width / 2) ** 2)
    k = int(np.ceil(np.nanmax(half) / cell)) + 1 if len(x) else 0
    off = np.arange(-k, k + 1)
    di, dj = np.meshgrid(off, off, indexing="ij")
    di, dj = di.ravel(), dj.ravel()
    rows_out, i_out, j_out = [], [], []
    for a in range(0, len(x), chunk):
        sl = slice(a, a + chunk)
        ci = np.floor(x[sl] / cell).astype(np.int64)
        cj = np.floor(y[sl] / cell).astype(np.int64)
        gi = ci[:, None] + di[None]
        gj = cj[:, None] + dj[None]
        dx = (gi + 0.5) * cell - x[sl, None]
        dy = (gj + 0.5) * cell - y[sl, None]
        c, s_ = np.cos(yaw[sl])[:, None], np.sin(yaw[sl])[:, None]
        u = dx * c + dy * s_
        v = -dx * s_ + dy * c
        inside = (np.abs(u) <= length[sl, None] / 2) & (np.abs(v) <= width[sl, None] / 2)
        inside[~inside.any(axis=1), len(di) // 2] = True
        r, q = np.nonzero(inside)
        rows_out.append(r + a)
        i_out.append(gi[r, q])
        j_out.append(gj[r, q])
    if not rows_out:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0, int)
    return np.concatenate(rows_out), np.concatenate(i_out), np.concatenate(j_out)


PET_COLUMNS = ["id_1", "id_2", "cls_1", "cls_2", "pet", "t_first_exit", "t_second_entry", "simultaneous", "x", "y",
               "angle"]


def pet_events(states: pd.DataFrame, max_pet: float = PET_MAX_S, cell: float = GRID_M,
               min_angle: float = MIN_CROSSING_DEG) -> pd.DataFrame:
    """Grid-based post-encroachment time between users whose paths cross a shared cell at an angle.

    Each occupant of a cell is compared with every later occupant that enters within max_pet of its exit. Overlapping
    occupancies give PET 0 with `simultaneous` set. x, y (cell centre) and angle belong to each pair's minimum PET."""
    st = states[np.hypot(states["vx"], states["vy"]) > MIN_MOVING_MPS]
    st = st.dropna(subset=["x", "y", "yaw", "length", "width"]).reset_index(drop=True)
    if st.empty:
        return pd.DataFrame(columns=PET_COLUMNS)
    rows, ii, jj = footprint_cells(st["x"].to_numpy(float), st["y"].to_numpy(float), st["yaw"].to_numpy(float),
                                   st["length"].to_numpy(float), st["width"].to_numpy(float), cell)
    occ = pd.DataFrame({"i": ii, "j": jj, "id": st["id"].to_numpy()[rows], "cls": st["cls"].to_numpy()[rows],
                        "t": st["t"].to_numpy()[rows],
                        "course": np.arctan2(st["vy"].to_numpy(), st["vx"].to_numpy())[rows]})
    span = occ.groupby(["i", "j", "id", "cls"], sort=False).agg(
        t_in=("t", "min"), t_out=("t", "max"), course=("course", "median")).reset_index()
    span = span.sort_values(["i", "j", "t_in"]).reset_index(drop=True)
    parts = []
    for k in range(1, len(span)):
        nxt = span.shift(-k)
        reach = (nxt["i"] == span["i"]) & (nxt["j"] == span["j"]) & (nxt["t_in"] <= span["t_out"] + max_pet)
        if not reach.any():
            break
        turn = np.degrees(np.abs((nxt["course"] - span["course"] + np.pi) % (2 * np.pi) - np.pi))
        ok = reach & (nxt["id"] != span["id"]) & (turn >= min_angle)
        a, b = span[ok], nxt[ok]
        if a.empty:
            continue
        gap = (b["t_in"] - a["t_out"]).to_numpy()
        first_smaller = a["id"].to_numpy() < b["id"].to_numpy()
        parts.append(pd.DataFrame({
            "id_1": np.where(first_smaller, a["id"], b["id"]), "id_2": np.where(first_smaller, b["id"], a["id"]),
            "cls_1": np.where(first_smaller, a["cls"], b["cls"]), "cls_2": np.where(first_smaller, b["cls"], a["cls"]),
            "pet": np.clip(gap, 0, None), "t_first_exit": a["t_out"].to_numpy(), "t_second_entry": b["t_in"].to_numpy(),
            "simultaneous": gap < 0, "x": (a["i"].to_numpy() + 0.5) * cell, "y": (a["j"].to_numpy() + 0.5) * cell,
            "angle": turn[ok].to_numpy()}))
    if not parts:
        return pd.DataFrame(columns=PET_COLUMNS)
    pairs = pd.concat(parts, ignore_index=True)
    best = pairs.loc[pairs.groupby(["id_1", "id_2"])["pet"].idxmin()]
    return best[PET_COLUMNS].reset_index(drop=True)


def from_fluid(df: pd.DataFrame, fps: float) -> pd.DataFrame:
    """Reference trajectories (FLUID columns) to engine states."""
    out = pd.DataFrame({"id": df["id"], "frame": df["frame"], "t": df["frame"] / fps, "x": df["cx_m"],
                        "y": df["cy_m"], "vx": df["vx"], "vy": df["vy"], "yaw": df["yaw"],
                        "length": df["length_med"], "width": df["width_med"], "cls": df["cls"]})
    return out.dropna(subset=["x", "y", "vx", "vy", "yaw", "length", "width"]).reset_index(drop=True)
