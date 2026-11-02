"""The web's Check a claim: jobs run one at a time under the daily budget, and the HTTP endpoints work end to end
with a fake desk run (no model, no network)."""
import json
import socket
import threading
import time
import urllib.request

import pytest

from nearmisslens import app, check
from nearmisslens.budget import DailyBudget
from nearmisslens.jobs import Busy, Jobs, Paused


def wait(jobs, job, s=5.0):
    t = time.time()
    while time.time() - t < s:
        rec = jobs.status(job)
        if rec["status"] != "running":
            return rec
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_one_job_at_a_time_and_the_budget_is_reserved_then_settled(tmp_path):
    gate = threading.Event()
    b = DailyBudget(usd=0.6, requests=10, path=tmp_path / "b.json")
    jobs = Jobs(lambda q: (gate.wait(5), {"status": "published", "cost_usd": {"meta": 0.12}})[1], b, 0.5, tmp_path / "j")
    job = jobs.submit({"input": "x"})
    assert jobs.status(job)["status"] == "running" and b.state()["usd"] == pytest.approx(0.5)
    with pytest.raises(Busy):
        jobs.submit({"input": "y"})
    gate.set()
    assert wait(jobs, job)["result"]["status"] == "published"
    assert b.state()["usd"] == pytest.approx(0.12)  # the reservation became the real cost
    with pytest.raises(Paused):  # 0.12 + 0.5 would pass the 0.6 cap
        jobs.submit({"input": "z"})


def test_a_failed_job_says_so_plainly_and_counts_its_reservation(tmp_path):
    b = DailyBudget(usd=5, requests=10, path=tmp_path / "b.json")
    jobs = Jobs(lambda q: 1 / 0, b, 0.5, tmp_path / "j")
    rec = wait(jobs, jobs.submit({}))
    assert rec["status"] == "failed" and "ZeroDivision" not in json.dumps(rec) and b.state()["usd"] == 0.5
    assert jobs.status("../../etc") is None and jobs.status("0" * 16) is None


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_check_endpoints_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("NML_RUNS", str(tmp_path))
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(check, "validate", lambda text, city, kind=None, photo=None:
                        (_ for _ in ()).throw(LookupError("no crash data")) if city == "la" else ("url", {}))
    monkeypatch.setattr(check, "check", lambda text, city, **k: {"status": "published", "corner": "A & B",
                                                                 "cost_usd": {"meta": 0.1}})
    monkeypatch.setattr(check, "cities", lambda: [{"id": "zz", "checkable": True}])
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            assert _call(base + "/cities") == (200, {"cities": [{"id": "zz", "checkable": True}]})
            break
        except OSError:
            time.sleep(0.05)
    assert _call(base + "/check", {"input": "https://example.org/a", "city": "la"})[0] == 422
    assert _call(base + "/check", {"input": ["x"], "city": "zz"})[0] == 400
    code, body = _call(base + "/check", {"input": "https://example.org/a", "city": "zz"})
    assert code == 202
    for _ in range(100):
        code, rec = _call(f"{base}/check/{body['job']}")
        if rec["status"] != "running":
            break
        time.sleep(0.05)
    assert code == 200 and rec["status"] == "done" and rec["result"]["corner"] == "A & B"
    assert _call(base + "/check/ffffffffffffffff")[0] == 404
