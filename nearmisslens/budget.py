"""A daily spending and request cap for the public endpoint, shared by every container.

Model calls reserve their worst-case cost before they run and settle the real cost after; deterministic requests
count against a request cap. On Modal the counters live in a modal.Dict (NML_BUDGET_DICT names it), so a second
container cannot double the cap; locally they live in a JSON file under the runs directory. Counters reset each UTC
day. No caller identity is stored: the caps are global, so no IP address is ever kept."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

from .config import SETTINGS

_LOCK = threading.Lock()


class DailyBudget:
    def __init__(self, usd: float | None = None, requests: int | None = None, path: Path | None = None, store=None):
        self.usd = float(os.environ.get("NML_DAILY_USD", "1.0")) if usd is None else usd
        self.requests = int(os.environ.get("NML_DAILY_REQUESTS", "300")) if requests is None else requests
        self.path = path or SETTINGS.runs_dir / "budget.json"
        self.store = store
        if self.store is None and os.environ.get("NML_BUDGET_DICT"):
            import modal
            self.store = modal.Dict.from_name(os.environ["NML_BUDGET_DICT"], create_if_missing=True)

    def _key(self) -> str:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()

    def _get(self) -> dict:
        if self.store is not None:
            return self.store.get(self._key(), {"usd": 0.0, "requests": 0})
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        return data.get(self._key(), {"usd": 0.0, "requests": 0})

    def _put(self, day: dict) -> None:
        if self.store is not None:
            self.store[self._key()] = day
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({self._key(): day}))

    def request(self) -> bool:
        """Count one request; False when today's request cap is reached."""
        with _LOCK:
            day = self._get()
            if day["requests"] >= self.requests:
                return False
            day["requests"] += 1
            self._put(day)
            return True

    def reserve(self, usd: float) -> bool:
        """Hold usd of today's model budget; False (and nothing held) when it would pass the cap."""
        with _LOCK:
            day = self._get()
            if day["usd"] + usd > self.usd:
                return False
            day["usd"] = round(day["usd"] + usd, 6)
            self._put(day)
            return True

    def settle(self, reserved: float, actual: float) -> None:
        """Replace a reservation with the real cost."""
        with _LOCK:
            day = self._get()
            day["usd"] = round(max(0.0, day["usd"] - reserved + actual), 6)
            self._put(day)

    def state(self) -> dict:
        return {**self._get(), "usd_cap": self.usd, "request_cap": self.requests, "day": self._key()}
