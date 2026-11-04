"""A daily spending and request cap for the public endpoint, shared by every container.

Model calls reserve their worst-case cost before they run and settle the real cost after; deterministic requests
count against a request cap. On Modal the counters live in a modal.Dict (NML_BUDGET_DICT names it), so a second
container cannot double the cap; locally they live in a JSON file under the runs directory. Counters reset each UTC
day. The caps are global; the per-visitor limit (VisitorLimit) tells visitors apart by a salted hash held in memory for
one hour and never written, so no IP address is stored."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import threading
import time
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

    def resets(self) -> dt.datetime:
        """When today's budget starts again: the next midnight, UTC (the day is the UTC date)."""
        today = dt.datetime.now(dt.timezone.utc).date()
        return dt.datetime.combine(today + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc)

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


class VisitorLimit:
    """At most `jobs` paid jobs per visitor in a rolling window, so one visitor cannot use up the day's budget.

    A visitor is a salted hash of their address; the salt is made at start-up and never saved, the hashes live only in
    memory and are dropped once their window has passed. Nothing is written to disk or logged."""

    def __init__(self, jobs: int | None = None, window_s: float = 3600.0):
        self.jobs = int(os.environ.get("NML_VISITOR_JOBS_PER_HOUR", "10")) if jobs is None else jobs
        self.window = window_s
        self._salt = secrets.token_bytes(16)
        self._seen: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, address: str, now: float | None = None) -> tuple[bool, int]:
        """(True, 0) and count one job, or (False, seconds until the visitor may start another)."""
        now = time.time() if now is None else now
        cut = now - self.window
        key = hashlib.sha256(self._salt + address.encode()).hexdigest()[:20]
        with self._lock:
            for k in [k for k, ts in self._seen.items() if ts[-1] <= cut]:
                del self._seen[k]
            ts = [t for t in self._seen.get(key, []) if t > cut]
            if len(ts) >= self.jobs:
                self._seen[key] = ts
                return False, int(ts[0] - cut) + 1
            self._seen[key] = ts + [now]
            return True, 0

    def refund(self, address: str) -> None:
        """Give back the visitor's latest job: a request that was refused or failed before any work counts for nothing."""
        key = hashlib.sha256(self._salt + address.encode()).hexdigest()[:20]
        with self._lock:
            ts = self._seen.get(key)
            if ts:
                ts.pop()
                if not ts:
                    del self._seen[key]
