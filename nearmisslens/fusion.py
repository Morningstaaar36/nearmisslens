"""Near-miss and crash fusion (NML-Bench T10): where will injury crashes happen next?

A site's crash history is a noisy signal: a few crashes a year at most. Near-misses are far more frequent. The fusion
method estimates each site's future injury-crash count with a negative binomial safety model whose prior mean uses
both the crash history and near-miss counts, then combines prior and history by Empirical Bayes (Hauer):
    EB = w * mu + (1 - w) * past_injury * (T_future / T_past),  w = 1 / (1 + mu / phi)
with phi the fitted negative binomial shape. The crash-only model is the same without near-miss inputs.

Test (registered in BENCH_PREREG T10): Washington DC, 100 m cells, residents' 2015 Vision Zero near-miss and safety
reports, crash history 2013-2016, target injury crashes 2017-2019 (and 2021-2024); models are fitted on 70% of 1 km
blocks and scored only on the other 30%."""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import spearmanr

from . import context
from .evaluate import RESULTS_DIR

DCGIS = "https://maps2.dcgis.dc.gov/dcgis/rest/services"
CRASHES = f"{DCGIS}/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query"
REPORTS = f"{DCGIS}/DDOT/VisionZero/FeatureServer/0/query"
INJ = ["MAJORINJURIES_PEDESTRIAN", "MINORINJURIES_PEDESTRIAN", "FATAL_PEDESTRIAN", "MAJORINJURIES_BICYCLIST",
       "MINORINJURIES_BICYCLIST", "FATAL_BICYCLIST", "MAJORINJURIES_DRIVER", "MINORINJURIES_DRIVER", "FATAL_DRIVER",
       "MAJORINJURIESPASSENGER", "MINORINJURIESPASSENGER", "FATALPASSENGER"]
LAT0, LON0 = 38.9, -77.03
CELL_M, BLOCK_M = 100.0, 1000.0
HISTORY = ("2013-01-01", "2016-12-31")
TARGETS = {"2017-2019": ("2017-01-01", "2019-12-31"), "2021-2024": ("2021-01-01", "2024-12-31")}
GROUPS = {"pedestrian": ("failure to stop for pedestrians", "blocking the crosswalk", "not enough time to cross",
                         "long wait to cross", "long distance to cross", "other walking issue", "poor visibility"),
          "speed_signal": ("speeding", "red light running", "stop sign running"),
          "cycling": ("other biking issue", "blocking the bikebox", "cyclist behavior")}
TEST_SHARE, SEED = 0.30, 0


def _pages(url: str, where: str, fields: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        js, _ = context.fetch(url, {"where": where, "outFields": fields, "returnGeometry": "true", "outSR": 4326,
                                    "f": "json", "resultOffset": offset, "resultRecordCount": 1000,
                                    "orderByFields": "OBJECTID"})
        feats = js.get("features", [])
        for f in feats:
            g = f.get("geometry") or {}
            rows.append({**f["attributes"], "lon": g.get("x"), "lat": g.get("y")})
        if not feats or not js.get("exceededTransferLimit"):
            return rows
        offset += len(feats)


def crashes(start: str, end: str) -> pd.DataFrame:
    """DC police crash records in [start, end], year by year so paging stays small."""
    out = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        a, b = max(start, f"{y}-01-01"), min(end, f"{y}-12-31")
        out += _pages(CRASHES, f"REPORTDATE >= DATE '{a}' AND REPORTDATE <= DATE '{b}'", ",".join(["OBJECTID"] + INJ))
    df = pd.DataFrame(out)
    df["injury"] = (df[INJ].fillna(0).astype(float).sum(axis=1) > 0).astype(int)
    return df.dropna(subset=["lat", "lon"])


def reports() -> pd.DataFrame:
    df = pd.DataFrame(_pages(REPORTS, "1=1", "OBJECTID,REQUESTTYPE,USERTYPE,REQUESTDATE"))
    t = df["REQUESTTYPE"].fillna("").str.lower()
    for g, kinds in GROUPS.items():
        df[g] = t.isin(kinds).astype(int)
    return df.dropna(subset=["lat", "lon"])


def _cell(df: pd.DataFrame) -> pd.DataFrame:
    x = (df["lon"] - LON0) * math.cos(math.radians(LAT0)) * 111_320
    y = (df["lat"] - LAT0) * 110_540
    return df.assign(cx=np.floor(x / CELL_M).astype(int), cy=np.floor(y / CELL_M).astype(int))


def _test_block(cx: int, cy: int) -> bool:
    bx, by = math.floor(cx * CELL_M / BLOCK_M), math.floor(cy * CELL_M / BLOCK_M)
    h = int(hashlib.sha256(f"{SEED}:{bx}:{by}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return h < TEST_SHARE


def table(target: str) -> pd.DataFrame:
    """One row per cell: history (all and injury crashes), near-miss reports by group, and the target count."""
    hist = _cell(crashes(*HISTORY))
    fut = _cell(crashes(*TARGETS[target]))
    rep = _cell(reports())
    h = hist.groupby(["cx", "cy"]).agg(past_all=("injury", "size"), past_injury=("injury", "sum"))
    f = fut.groupby(["cx", "cy"]).agg(future_injury=("injury", "sum"))
    r = rep.groupby(["cx", "cy"]).agg(reports=("OBJECTID", "size"), **{f"rep_{g}": (g, "sum") for g in GROUPS})
    t = h.join(f, how="outer").join(r, how="outer").fillna(0).reset_index()
    t["block"] = [f"{math.floor(a * CELL_M / BLOCK_M)}:{math.floor(b * CELL_M / BLOCK_M)}" for a, b in zip(t["cx"], t["cy"])]
    t["test"] = [_test_block(a, b) for a, b in zip(t["cx"], t["cy"])]
    return t


def _nb_nll(params: np.ndarray, X: np.ndarray, y: np.ndarray) -> float:
    beta, log_phi = params[:-1], params[-1]
    mu = np.exp(np.clip(X @ beta, -20, 20))
    phi = math.exp(log_phi)
    return -float(np.sum(gammaln(y + phi) - gammaln(phi) - gammaln(y + 1)
                         + phi * np.log(phi / (phi + mu)) + y * np.log(mu / (phi + mu))))


def fit_nb(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    x0 = np.zeros(X.shape[1] + 1)
    x0[0] = math.log(max(y.mean(), 1e-3))
    res = minimize(_nb_nll, x0, args=(X, y), method="L-BFGS-B")
    return res.x[:-1], math.exp(res.x[-1])


FEATURES = {"M1_crash_eb": ["past_injury", "past_all"],
            "M3_fusion_eb": ["past_injury", "past_all", "reports", "rep_pedestrian", "rep_speed_signal", "rep_cycling"]}


def _design(t: pd.DataFrame, cols: list[str]) -> np.ndarray:
    return np.column_stack([np.ones(len(t))] + [np.log1p(t[c].to_numpy(float)) for c in cols])


def predict(t: pd.DataFrame, target: str) -> pd.DataFrame:
    tr, te = t[~t["test"]], t[t["test"]].copy()
    years_hist = 4.0
    years_fut = {"2017-2019": 3.0, "2021-2024": 4.0}[target]
    te["M0_crash_history"] = te["past_injury"]
    te["M2_reports_only"] = te["reports"]
    fitted = {}
    for name, cols in FEATURES.items():
        beta, phi = fit_nb(_design(tr, cols), tr["future_injury"].to_numpy(float))
        mu = np.exp(_design(te, cols) @ beta)
        w = 1.0 / (1.0 + mu / phi)
        te[name] = w * mu + (1 - w) * te["past_injury"] * (years_fut / years_hist)
        te[f"{name}_mu"] = mu
        fitted[name] = {"beta": dict(zip(["intercept"] + cols, np.round(beta, 4).tolist())), "phi": round(phi, 4)}
    te.attrs["fitted"] = fitted
    return te


def _top(scores: np.ndarray, truth: np.ndarray, share: float, rng=None) -> float:
    k = max(1, int(round(share * len(scores))))
    # ties broken at random (seeded) so a model is not rewarded for many equal scores
    jitter = (rng or np.random.default_rng(SEED)).random(len(scores)) * 1e-9
    top_pred = set(np.argsort(-(scores + jitter))[:k])
    top_true = set(np.argsort(-(truth + jitter))[:k])
    return len(top_pred & top_true) / k


def _nb_loglik(mu: np.ndarray, y: np.ndarray, phi: float) -> float:
    return float(np.mean(gammaln(y + phi) - gammaln(phi) - gammaln(y + 1)
                         + phi * np.log(phi / (phi + mu)) + y * np.log(np.maximum(mu, 1e-9) / (phi + mu))))


MODELS = ("M0_crash_history", "M1_crash_eb", "M2_reports_only", "M3_fusion_eb")


def evaluate(te: pd.DataFrame, n_boot: int = 2000) -> dict:
    y = te["future_injury"].to_numpy(float)
    out = {"test_cells": int(len(te)), "test_blocks": int(te["block"].nunique()),
           "future_injury_crashes": int(y.sum()), "models": {}}
    for m in MODELS:
        s = te[m].to_numpy(float)
        out["models"][m] = {"top5_precision": _top(s, y, 0.05), "top10_precision": _top(s, y, 0.10),
                            "spearman": float(spearmanr(s, y).statistic)}
    rng = np.random.default_rng(SEED)
    blocks = te["block"].unique()
    idx = {b: np.flatnonzero(te["block"].to_numpy() == b) for b in blocks}
    diffs = []
    for _ in range(n_boot):
        pick = np.concatenate([idx[b] for b in rng.choice(blocks, len(blocks), replace=True)])
        yy = y[pick]
        diffs.append(_top(te["M3_fusion_eb"].to_numpy(float)[pick], yy, 0.05, rng)
                     - _top(te["M1_crash_eb"].to_numpy(float)[pick], yy, 0.05, rng))
    out["top5_diff_fusion_minus_crash_ci95"] = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
    m1, m3 = out["models"]["M1_crash_eb"], out["models"]["M3_fusion_eb"]
    out["claim_fusion_better"] = bool(m3["top5_precision"] > m1["top5_precision"]
                                      and out["top5_diff_fusion_minus_crash_ci95"][0] > 0)
    return out


def run() -> dict:
    res = {}
    for target in TARGETS:
        t = table(target)
        te = predict(t, target)
        r = evaluate(te)
        r["fitted"] = te.attrs["fitted"]
        r["cells"] = int(len(t))
        r["train_cells"] = int((~t["test"]).sum())
        res[target] = r
        print(target, json.dumps({k: v for k, v in r.items() if k != "fitted"}, default=float), flush=True)
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "fusion_dc.json").write_text(json.dumps(res, indent=1, default=float))
    return res
