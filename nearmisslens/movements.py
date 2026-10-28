"""Junction routes from tracks alone: approach and exit arm, turning movement, and the signal state on entry.

Positions are in a north-up metric frame (the GeoTIFF base map), so arms are compass directions from the junction
centre. Traffic drives on the right."""
from __future__ import annotations

import numpy as np
import pandas as pd

ARMS = ("N", "E", "S", "W")
MIN_ARM_DIST_M = 15.0
ENTRY_RADIUS_M = 20.0
ENTRY_MIN_SPEED = 2.0
ROUTE_COLUMNS = ["id", "cls", "entry_arm", "exit_arm", "movement", "t_entry"]


def junction_centre(states: pd.DataFrame) -> tuple[float, float]:
    return float(states["x"].median()), float(states["y"].median())


def arm_of(dx, dy) -> np.ndarray:
    bearing = np.degrees(np.arctan2(dx, dy)) % 360
    return np.asarray(ARMS)[((bearing + 45) // 90).astype(int) % 4]


def movement(entry_arm: str, exit_arm: str) -> str:
    """Clockwise arm steps from entry to exit: 1 left, 2 through, 3 right, 0 u-turn (right-hand traffic)."""
    if entry_arm not in ARMS or exit_arm not in ARMS:
        return "unknown"
    return {0: "u_turn", 1: "left", 2: "through", 3: "right"}[(ARMS.index(exit_arm) - ARMS.index(entry_arm)) % 4]


def routes(states: pd.DataFrame, centre: tuple[float, float] | None = None) -> pd.DataFrame:
    """Per track: arms from its first and last positions (unknown when closer than MIN_ARM_DIST_M to the centre),
    movement, and entry time (see entry_time)."""
    if states.empty:
        return pd.DataFrame(columns=ROUTE_COLUMNS)
    cx, cy = centre or junction_centre(states)
    s = states.sort_values("t")
    g = s.groupby("id", sort=False)
    first, last = g[["x", "y"]].first(), g[["x", "y"]].last()
    d0 = np.hypot(first["x"] - cx, first["y"] - cy)
    d1 = np.hypot(last["x"] - cx, last["y"] - cy)
    entry = np.where(d0 > MIN_ARM_DIST_M, arm_of(first["x"] - cx, first["y"] - cy), "unknown")
    exit_ = np.where(d1 > MIN_ARM_DIST_M, arm_of(last["x"] - cx, last["y"] - cy), "unknown")
    near = {uid: entry_time(tr["t"].to_numpy(float), np.hypot(tr["x"] - cx, tr["y"] - cy).to_numpy(float),
                            np.hypot(tr["vx"], tr["vy"]).to_numpy(float)) for uid, tr in g}
    out = pd.DataFrame({"id": first.index, "cls": g["cls"].first().to_numpy(), "entry_arm": entry, "exit_arm": exit_})
    out["movement"] = [movement(a, b) for a, b in zip(out["entry_arm"], out["exit_arm"])]
    out["t_entry"] = out["id"].map(near)
    return out[ROUTE_COLUMNS].reset_index(drop=True)


def entry_time(t: np.ndarray, dist: np.ndarray, speed: np.ndarray) -> float:
    """Time the user entered the junction on its passage: within ENTRY_RADIUS_M of the centre, on the uninterrupted
    stretch at ENTRY_MIN_SPEED or more that contains its closest approach. A vehicle that stops in a queue inside the
    radius enters when it moves off."""
    if len(t) == 0 or dist.min() > ENTRY_RADIUS_M:
        return float("nan")
    k = int(np.argmin(dist))
    start = k
    while start > 0 and speed[start - 1] >= ENTRY_MIN_SPEED:
        start -= 1
    inside = np.nonzero(dist[start:k + 1] <= ENTRY_RADIUS_M)[0]
    return float(t[start + inside[0]]) if len(inside) else float("nan")


def signal_group(move: str) -> str | None:
    return {"left": "l", "u_turn": "l", "through": "s", "right": "r"}.get(move)


def entry_signal(signals: pd.DataFrame, route) -> str | None:
    """Signal state (G, y, r) of the route's approach and movement when it entered the junction; None when the
    movement has no signal group at this site or the entry time is unknown."""
    group = signal_group(route.movement)
    if group is None or route.entry_arm not in ARMS or route.t_entry != route.t_entry:
        return None
    rows = signals[(signals["direction"] == route.entry_arm) & (signals["turn"] == group)
                   & (signals["begin_time"] <= route.t_entry) & (route.t_entry < signals["end_time"])]
    return str(rows["state"].iloc[0]) if len(rows) else None


def route_accuracy(states: pd.DataFrame, labels: pd.Series) -> dict:
    """Agreement of derived entry-exit arms with labelled routes ("N-E" style, per id), excluding unknown arms."""
    r = routes(states).set_index("id")
    lab = labels.reindex(r.index)
    pred = r["entry_arm"] + "-" + r["exit_arm"]
    ok = lab.notna() & ~lab.astype(str).str.contains("Unknown") & ~pred.str.contains("unknown")
    n = int(ok.sum())
    return {"tracks": n, "route_accuracy": float((pred[ok] == lab[ok]).mean()) if n else float("nan"),
            "entry_arm_accuracy": float((r["entry_arm"][ok] == lab[ok].str.split("-").str[0]).mean()) if n else float("nan")}
