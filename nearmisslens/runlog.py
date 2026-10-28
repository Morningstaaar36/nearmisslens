from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .config import ROOT, SETTINGS


def _commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def log_metrics(stage: str, clip: str, metrics: dict, path: Path | None = None) -> dict:
    row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "commit": _commit(), "stage": stage, "clip": clip, **metrics}
    p = Path(path or SETTINGS.runs_dir / "metrics.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, default=float) + "\n")
    return row


def read_metrics(path: Path | None = None) -> list[dict]:
    p = Path(path or SETTINGS.runs_dir / "metrics.jsonl")
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def metrics_markdown(rows: list[dict]) -> str:
    latest: dict[tuple, dict] = {}
    for r in rows:
        latest[(r["stage"], r["clip"], r.get("class", ""))] = r
    keys = ["recall", "precision", "position_rmse_m", "speed_mae_mps", "idf1", "id_switches_per_min", "f1", "median_m", "usd"]
    lines = ["| stage | clip | class | " + " | ".join(keys) + " | commit |", "|" + "---|" * (len(keys) + 4)]
    for (stage, clip, cls), r in sorted(latest.items()):
        vals = [f"{r[k]:.3f}" if isinstance(r.get(k), (int, float)) else "" for k in keys]
        lines.append(f"| {stage} | {clip} | {cls} | " + " | ".join(vals) + f" | {r['commit']} |")
    return "\n".join(lines) + "\n"
