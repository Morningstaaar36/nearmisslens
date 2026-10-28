from __future__ import annotations

import json
import threading
import time
from pathlib import Path

TOKEN_USD_PER_M = {
    "muse-spark-1.3": (1.25, 4.25, 0.15),
    "muse-spark-1.3-contributor": (0.10, 0.20, 0.002),
    "muse-wonder-1.0": (4.00, 20.00, 0.20),
}
SAM_FRAME_USD = 0.0002
SAM_MIN_FRAMES = 50
SAM_IMAGE_USD = 0.0025
IMAGE_USD = 0.01
VOICE_USD_PER_HOUR = 0.18


class BudgetExceeded(RuntimeError):
    pass


def sam_video_usd(frames: int) -> float:
    return max(frames, SAM_MIN_FRAMES) * SAM_FRAME_USD


def token_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    inp, out, cached = TOKEN_USD_PER_M[model]
    return ((input_tokens - cached_tokens) * inp + cached_tokens * cached + output_tokens * out) / 1e6


def voice_usd(seconds: float) -> float:
    return int(seconds) / 3600 * VOICE_USD_PER_HOUR


class CostMeter:
    def __init__(self, ledger: Path, cap_usd: float):
        self.ledger = Path(ledger)
        self.cap = cap_usd
        self._lock = threading.Lock()
        self._reserved = 0.0

    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        return sum(json.loads(line)["usd"] for line in self.ledger.read_text().splitlines() if line.strip())

    def check(self, estimate_usd: float, what: str) -> None:
        """Raise if the estimate does not fit under the cap, counting spend and in-flight reservations."""
        with self._lock:
            committed = self.spent() + self._reserved
            if committed + estimate_usd > self.cap:
                raise BudgetExceeded(f"{what}: ${estimate_usd:.4f} would exceed the ${self.cap:.2f} cap "
                                     f"(spent and reserved ${committed:.4f})")

    def reserve(self, estimate_usd: float, what: str) -> None:
        """Atomically check the cap and hold the estimate until release() or record()."""
        with self._lock:
            committed = self.spent() + self._reserved
            if committed + estimate_usd > self.cap:
                raise BudgetExceeded(f"{what}: ${estimate_usd:.4f} would exceed the ${self.cap:.2f} cap "
                                     f"(spent and reserved ${committed:.4f})")
            self._reserved += estimate_usd

    def release(self, estimate_usd: float) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - estimate_usd)

    def record(self, model: str, usd: float, what: str, **usage) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        row = {"t": time.time(), "model": model, "usd": round(usd, 6), "what": what, **usage}
        with self._lock, self.ledger.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def summary(self) -> dict:
        by_model: dict[str, float] = {}
        if self.ledger.exists():
            for line in self.ledger.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    by_model[row["model"]] = by_model.get(row["model"], 0.0) + row["usd"]
        return {"spent_usd": round(sum(by_model.values()), 6), "cap_usd": self.cap,
                "by_model": {k: round(v, 6) for k, v in sorted(by_model.items())}}
