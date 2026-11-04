"""Background jobs for the web's "Check a claim": one desk case at a time, in a thread, polled by id.

A case takes minutes (web search, the city's open data, the gates), so POST /check returns a job id at once and
GET /check/<id> reports "running" until the result is ready. At most one job runs at a time; another request while it
runs gets a plain "busy" answer. In public mode each job reserves its worst-case Meta cost from the shared daily
budget before it starts and settles the real cost after, so the daily cap holds however many people try it. Jobs
and their results are kept for 24 hours under runs/checks/jobs/, with no caller identity."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

from .config import SETTINGS

KEEP_S = 24 * 3600
MAX_RUN_S = 45 * 60  # a job "running" longer than this, or not running in this process, stopped (a restart)


class Busy(RuntimeError):
    pass


class Paused(RuntimeError):
    pass


class Jobs:
    def __init__(self, runner, budget=None, reserve_usd: float = 0.50, store: Path | None = None, slots: int = 1,
                 busy: str = "another check is running; try again in a few minutes", plain: tuple = ()):
        """runner(q) -> result dict (check.check's); budget: a DailyBudget in public mode, else None; slots: how many
        jobs may run at once; plain: exception types whose message is already a plain sentence for the visitor."""
        self.runner, self.budget, self.reserve_usd = runner, budget, reserve_usd
        self.store = store or SETTINGS.runs_dir / "checks" / "jobs"
        self.slots, self.busy, self.plain = slots, busy, plain
        self.lock = threading.Lock()
        self.running: set[str] = set()
        self.done = threading.Condition(self.lock)

    def _path(self, job: str) -> Path:
        return self.store / f"{job}.json"

    def _write(self, job: str, rec: dict) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        tmp = self._path(job).with_suffix(".tmp")  # written whole, then swapped in, so a poll never reads half a file
        tmp.write_text(json.dumps(rec, default=str))
        os.replace(tmp, self._path(job))

    def _prune(self) -> None:
        for p in self.store.glob("*.json") if self.store.exists() else []:
            if time.time() - p.stat().st_mtime > KEEP_S:
                p.unlink(missing_ok=True)

    def submit(self, q: dict) -> str:
        """Start a job for an already validated request; Busy if one is running, Paused if today's budget is used."""
        with self.lock:
            if len(self.running) >= self.slots:
                raise Busy(self.busy)
            if self.budget is not None and not self.budget.reserve(self.reserve_usd):
                raise Paused("checks are paused for today (the daily model budget is used up); saved cases stay open")
            self._prune()
            job = secrets.token_hex(8)
            self.running.add(job)
            self._write(job, {"status": "running", "started": time.time()})
        threading.Thread(target=self._run, args=(job, q), daemon=True).start()
        return job

    def _run(self, job: str, q: dict) -> None:
        started, spent = time.time(), 0.0
        try:
            result = self.runner(q)
            spent = sum(float(v or 0.0) for v in (result.get("cost_usd") or {}).values())  # every model's dollars
            rec = {"status": "done", "started": started, "result": result}
        except self.plain as e:  # a plain refusal (a place not found, outside the cities): said as it is, nothing spent
            rec = {"status": "failed", "started": started, "error": str(e), "plain": True}
        except Exception as e:  # the visitor gets a plain sentence; the operator's log gets the cause
            print(f"{time.strftime('%H:%M:%S')} job failed: {type(e).__name__}: {e}", flush=True)
            spent = self.reserve_usd  # unknown spend counts as the whole reservation
            why = ("the model budget ran out while it worked; try again tomorrow, saved results stay open"
                   if type(e).__name__ == "BudgetExceeded" else
                   "it could not finish (a public data source did not answer); try again later")
            rec = {"status": "failed", "started": started, "error": why}
        finally:
            if self.budget is not None:
                self.budget.settle(self.reserve_usd, spent)
        rec["seconds"] = round(time.time() - started, 1)
        self._write(job, rec)
        with self.lock:
            self.running.discard(job)
            self.done.notify_all()

    def wait(self, job: str, seconds: float) -> dict | None:
        """The job's record once it has finished, waiting at most `seconds`; None while it still runs."""
        end = time.time() + seconds
        with self.lock:
            while job in self.running and time.time() < end:
                self.done.wait(max(0.0, end - time.time()))
        return self.status(job) if job not in self.running else None

    def status(self, job: str) -> dict | None:
        if not job.isalnum() or len(job) != 16:
            return None
        alive = job in self.running  # asked before reading: a job writes its result before it leaves the set
        p = self._path(job)
        if not p.exists():
            return None
        rec = json.loads(p.read_text())
        if rec["status"] == "running":
            rec["seconds"] = round(time.time() - rec["started"], 1)
            if not alive or rec["seconds"] > MAX_RUN_S:  # the server restarted, or the job hung
                return {"status": "failed", "seconds": rec["seconds"],
                        "error": "it stopped before it finished (the server restarted); try again"}
        return rec
