from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

MATCH_M = {"vehicle": 2.0, "two_wheeler": 1.5, "pedestrian": 1.0}


def frame_matches(pred: pd.DataFrame, ref: pd.DataFrame, cls: str) -> pd.DataFrame:
    thr = MATCH_M[cls]
    P = pred[pred["cls"] == cls]
    R = ref[ref["cls"] == cls]
    out = []
    pf = dict(tuple(P.groupby("frame")))
    for frame, r in R.groupby("frame"):
        p = pf.get(frame)
        if p is None or p.empty:
            continue
        D = np.linalg.norm(p[["x", "y"]].to_numpy()[:, None] - r[["x", "y"]].to_numpy()[None], axis=2)
        i, j = linear_sum_assignment(D)
        ok = D[i, j] <= thr
        for a, b, d in zip(i[ok], j[ok], D[i, j][ok]):
            out.append((frame, p["id"].iloc[a], r["id"].iloc[b], d, p.index[a], r.index[b]))
    return pd.DataFrame(out, columns=["frame", "pred_id", "ref_id", "dist", "pi", "ri"])


def tracking_metrics(pred: pd.DataFrame, ref: pd.DataFrame, cls: str, frames: set[int] | None = None) -> dict:
    if frames is not None:
        pred = pred[pred["frame"].isin(frames)]
        ref = ref[ref["frame"].isin(frames)]
    m = frame_matches(pred, ref, cls)
    n_ref = int((ref["cls"] == cls).sum())
    n_pred = int((pred["cls"] == cls).sum())
    tp = len(m)
    res = {"class": cls, "ref_points": n_ref, "pred_points": n_pred, "recall": tp / n_ref if n_ref else float("nan"),
           "precision": tp / n_pred if n_pred else float("nan")}
    if tp:
        res["position_rmse_m"] = float(np.sqrt(np.mean(m["dist"] ** 2)))
        best: dict = {}
        for rid, g in m.groupby("ref_id"):
            best[rid] = Counter(g["pred_id"]).most_common(1)[0][0]
        idtp = int(sum((g["pred_id"] == best[rid]).sum() for rid, g in m.groupby("ref_id")))
        res["idf1"] = 2 * idtp / (n_ref + n_pred) if (n_ref + n_pred) else float("nan")
        switches = 0
        for rid, g in m.sort_values("frame").groupby("ref_id"):
            ids = g["pred_id"].to_numpy()
            switches += int((ids[1:] != ids[:-1]).sum())
        minutes = (ref["frame"].max() - ref["frame"].min() + 1) / 600.0 if len(ref) else 1.0
        res["id_switches_per_min"] = switches / max(minutes, 1e-9)
        if "speed" in ref.columns and {"vx", "vy"} <= set(pred.columns):
            ps = np.hypot(pred.loc[m["pi"], "vx"].to_numpy(), pred.loc[m["pi"], "vy"].to_numpy())
            rs = ref.loc[m["ri"], "speed"].to_numpy()
            res["speed_mae_mps"] = float(np.nanmean(np.abs(ps - rs)))
            res["speed_bias_mps"] = float(np.nanmean(ps - rs))
    return res


def id_map(pred: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """Majority mapping from predicted track id to reference id, across all classes."""
    votes: dict = defaultdict(Counter)
    for cls in MATCH_M:
        m = frame_matches(pred, ref, cls)
        for p, r in zip(m["pred_id"], m["ref_id"]):
            votes[p][r] += 1
    return {p: c.most_common(1)[0][0] for p, c in votes.items()}


def event_metrics(pred_ev: pd.DataFrame, ref_ev: pd.DataFrame, pmap: dict, tol_frames: int = 10) -> dict:
    """Events match when the mapped pair is the same and the intervals overlap within the tolerance."""
    if ref_ev.empty and pred_ev.empty:
        return {"ref_events": 0, "pred_events": 0, "tp": 0, "precision": float("nan"), "recall": float("nan"), "f1": float("nan")}
    used = set()
    tp = 0
    ref_by_pair = defaultdict(list)
    for k, r in ref_ev.iterrows():
        ref_by_pair[frozenset((r["id_1"], r["id_2"]))].append((k, r))
    for _, p in pred_ev.iterrows():
        pair = frozenset((pmap.get(p["id_1"]), pmap.get(p["id_2"])))
        for k, r in ref_by_pair.get(pair, []):
            if k in used:
                continue
            if p["frame_start"] <= r["frame_end"] + tol_frames and r["frame_start"] <= p["frame_end"] + tol_frames:
                used.add(k)
                tp += 1
                break
    prec = tp / len(pred_ev) if len(pred_ev) else float("nan")
    rec = tp / len(ref_ev) if len(ref_ev) else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if prec and rec and prec + rec > 0 else 0.0
    return {"ref_events": int(len(ref_ev)), "pred_events": int(len(pred_ev)), "tp": tp, "precision": prec, "recall": rec, "f1": f1}
