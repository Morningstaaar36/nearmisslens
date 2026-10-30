from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SETTINGS

VEHICLE = {"car", "van", "truck", "bus", "tricycle", "trailer"}
TWO_WHEELER = {"moped"}
PEDESTRIAN = {"pedestrian", "pedestrain"}

TRAJ_COLUMNS = ["frame", "id", "type", "isReal", "cx", "cy", "w", "h", "r", "cx_m", "cy_m",
                "length_med", "width_med", "time", "speed", "vx", "vy", "yaw", "overall_direction"]


def road_user_class(fluid_type: str) -> str:
    t = fluid_type.strip().lower()
    if t in VEHICLE:
        return "vehicle"
    if t in TWO_WHEELER:
        return "two_wheeler"
    if t in PEDESTRIAN:
        return "pedestrian"
    return "other"


@dataclass(frozen=True)
class Clip:
    site: str
    stem: str
    video: Path
    root: Path

    @property
    def traj_path(self) -> Path:
        return self.root / "derived_data" / "traj" / f"{self.stem}_Traj.csv"

    @property
    def signal_path(self) -> Path:
        return self.root / "derived_data" / "signal" / f"{self.stem}_signal.csv"

    @property
    def base_map(self) -> Path:
        return self.root / "derived_data" / "map" / f"{self.site}.tif"

    @property
    def conflict_path(self) -> Path:
        return self.root / "derived_data" / "conflict" / f"{self.site}_conflict.csv"


def clip(site: str, stem: str, data_dir: Path | None = None) -> Clip:
    base = Path(data_dir or SETTINGS.data_dir) / "fluid"
    return Clip(site, stem, base / f"{site}_{stem}.mp4", base / site)


DEV = ("FIDRT", "20250525_video")
TEST = ("FIDRT", "20250526_video")
HELDOUT = ("FI", "20250530_video-1")
# Every FLUID flight (site, stem): 3 at FIDRT, 8 at FI, 3 at TI. NML-Bench uses all of them.
FLIGHTS = (("FIDRT", "20250120_video"), DEV, TEST,
           ("FI", "20250120_video"), ("FI", "20250121_video-1"), ("FI", "20250121_video-2"), ("FI", "20250121_video-3"),
           ("FI", "20250525_video-1"), ("FI", "20250525_video-2"), HELDOUT, ("FI", "20250530_video-2"),
           ("TI", "20250529_video-1"), ("TI", "20250529_video-2"), ("TI", "20250529_video-3"))


def load_trajectories(c: Clip, real_only: bool = False) -> pd.DataFrame:
    df = pd.read_csv(c.traj_path, usecols=TRAJ_COLUMNS)
    df["cls"] = df["type"].map(road_user_class)
    if real_only:
        df = df[df["isReal"] == 1]
    return df.reset_index(drop=True)


def load_signals(c: Clip) -> pd.DataFrame:
    return pd.read_csv(c.signal_path)


def signal_state(signals: pd.DataFrame, t: float) -> dict[tuple[str, str], str]:
    active = signals[(signals["begin_time"] <= t) & (t < signals["end_time"])]
    return {(r.direction, r.turn): r.state for r in active.itertuples()}


def has_right_turn_control(signals: pd.DataFrame) -> bool:
    return bool((signals["turn"] == "r").any())


def pixel_to_metre_pairs(df: pd.DataFrame, n: int = 2000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    real = df[df["isReal"] == 1]
    s = real.sample(min(n, len(real)), random_state=seed)
    return s[["cx", "cy"]].to_numpy(float), s[["cx_m", "cy_m"]].to_numpy(float)
