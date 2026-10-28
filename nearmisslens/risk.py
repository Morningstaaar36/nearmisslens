from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2

from .conflicts import TTC_MAX_S, ttc_batch

STATE_COLS = ["x", "y", "vx", "vy", "yaw", "length", "width"]


def ttc_probability(states: pd.DataFrame, events: pd.DataFrame, sigma_pos: float, sigma_vel: float,
                    n: int = 200, threshold: float = TTC_MAX_S, seed: int = 0) -> pd.Series:
    """P(TTC <= threshold) at each event's minimum-TTC frame under Gaussian position and velocity noise."""
    rng = np.random.default_rng(seed)
    idx = states.set_index(["id", "frame"])
    probs = []
    for e in events.itertuples():
        f = int(round(e.t_min_ttc * 10))
        try:
            a = idx.loc[(e.id_1, f), STATE_COLS].to_numpy(float)
            b = idx.loc[(e.id_2, f), STATE_COLS].to_numpy(float)
        except KeyError:
            probs.append(np.nan)
            continue
        A = np.repeat(a[None], n, 0)
        B = np.repeat(b[None], n, 0)
        for M in (A, B):
            M[:, 0:2] += rng.normal(0, sigma_pos, (n, 2))
            M[:, 2:4] += rng.normal(0, sigma_vel, (n, 2))
        probs.append(float((ttc_batch(A, B) <= threshold).mean()))
    return pd.Series(probs, index=events.index, name="p_ttc")


def pet_sigma(pet: pd.DataFrame, states: pd.DataFrame, sigma_pos: float) -> pd.Series:
    """First-order PET uncertainty: position error divided by the users' speeds at the shared cell."""
    speed = np.hypot(states["vx"], states["vy"]).groupby(states["id"]).median()
    s1 = pet["id_1"].map(speed).clip(lower=0.5)
    s2 = pet["id_2"].map(speed).clip(lower=0.5)
    return np.sqrt((sigma_pos / s1) ** 2 + (sigma_pos / s2) ** 2).rename("pet_sigma_s")


def poisson_ci(k: int, conf: float = 0.95) -> tuple[float, float]:
    a = 1 - conf
    lo = 0.0 if k == 0 else chi2.ppf(a / 2, 2 * k) / 2
    hi = chi2.ppf(1 - a / 2, 2 * k + 2) / 2
    return float(lo), float(hi)


def hotspots(events: pd.DataFrame, states: pd.DataFrame, cell_m: float = 10.0, min_events: int = 1) -> pd.DataFrame:
    """Conflict rate per 1,000 road users passing through each cell, with exact Poisson 95% intervals."""
    if events.empty:
        return pd.DataFrame(columns=["cx", "cy", "events", "users", "rate_per_1000", "ci_low", "ci_high"])
    users = states.assign(cx=np.floor(states["x"] / cell_m), cy=np.floor(states["y"] / cell_m)) \
        .groupby(["cx", "cy"])["id"].nunique().rename("users")
    ev = events.assign(cx=np.floor(events["x"] / cell_m), cy=np.floor(events["y"] / cell_m)) \
        .groupby(["cx", "cy"]).size().rename("events")
    h = pd.concat([ev, users], axis=1).dropna().reset_index()
    h = h[h["events"] >= min_events]
    h["rate_per_1000"] = 1000 * h["events"] / h["users"]
    ci = h["events"].astype(int).map(poisson_ci)
    h["ci_low"] = [1000 * lo / u for (lo, _), u in zip(ci, h["users"])]
    h["ci_high"] = [1000 * hi / u for (_, hi), u in zip(ci, h["users"])]
    h["cx"] = (h["cx"] + 0.5) * cell_m
    h["cy"] = (h["cy"] + 0.5) * cell_m
    return h.sort_values("rate_per_1000", ascending=False).reset_index(drop=True)


def event_locations(events: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    """Midpoint of the two users at each event's critical moment."""
    idx = states.set_index(["id", "frame"])[["x", "y"]]
    xs, ys = [], []
    for e in events.itertuples():
        f = int(round(e.t_min_ttc * 10))
        try:
            p = (idx.loc[(e.id_1, f)].to_numpy() + idx.loc[(e.id_2, f)].to_numpy()) / 2
        except KeyError:
            p = (np.nan, np.nan)
        xs.append(p[0])
        ys.append(p[1])
    return events.assign(x=xs, y=ys)
