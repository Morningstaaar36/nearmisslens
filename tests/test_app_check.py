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
            code, d = _call(base + "/cities")
            break
        except OSError:
            time.sleep(0.05)
    assert code == 200 and d["cities"] == [{"id": "zz", "checkable": True}]
    assert d["limits"] == {"program_items": app.PROGRAM_ITEMS}
    assert d["service"]["records_as_of"] and d["service"]["repository"].startswith("https://")
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


def test_jobs_wait_returns_quick_results_and_none_while_running(tmp_path):
    gate = threading.Event()
    jobs = Jobs(lambda q: (gate.wait(5), {"ok": q["n"]})[1], None, 0.0, tmp_path / "j", slots=2, busy="busy now")
    a, b = jobs.submit({"n": 1}), jobs.submit({"n": 2})  # two slots: both start
    with pytest.raises(Busy, match="busy now"):
        jobs.submit({"n": 3})
    assert jobs.wait(a, 0.05) is None  # still running: the caller hands out the job id instead
    gate.set()
    assert jobs.wait(a, 5)["result"] == {"ok": 1} and jobs.wait(b, 5)["result"] == {"ok": 2}


def test_a_plain_refusal_is_said_as_it_is_and_costs_nothing(tmp_path):
    b = DailyBudget(usd=5, requests=10, path=tmp_path / "b.json")
    jobs = Jobs(lambda q: (_ for _ in ()).throw(ValueError("no such intersection was found")), b, 0.5, tmp_path / "j",
                plain=(ValueError,))
    rec = jobs.wait(jobs.submit({}), 5)
    assert rec["status"] == "failed" and rec["plain"] and rec["error"] == "no such intersection was found"
    assert b.state()["usd"] == 0.0


def test_a_job_left_running_by_a_restart_reads_as_stopped(tmp_path):
    store = tmp_path / "j"
    store.mkdir()
    (store / "0123456789abcdef.json").write_text(json.dumps({"status": "running", "started": time.time() - 30}))
    rec = Jobs(lambda q: {}, None, 0.0, store).status("0123456789abcdef")  # a new process: not running here
    assert rec["status"] == "failed" and "restarted" in rec["error"]


def test_engineer_answers_quick_corners_inline_and_slow_ones_as_a_job(monkeypatch, tmp_path):
    from nearmisslens import brief, context, engineer
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(app, "ENGINEER_WAIT_S", 3.0)  # a quick answer under a loaded machine; the slow one waits on an event
    slow = threading.Event()
    monkeypatch.setattr(brief, "geocode", lambda a: (_ for _ in ()).throw(ValueError("could not find that place"))
                        if a.startswith("Nowhere") else (1.0, 2.0, a))
    monkeypatch.setattr(context, "city_of", lambda lat, lon: "zz")
    monkeypatch.setattr(engineer, "investigate", lambda desk, a, name, lat, lon:
                        (slow.wait(5) if a.startswith("Slow") else None, {"junction": {"name": name}})[1])
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _call(base + "/cities")
            break
        except OSError:
            time.sleep(0.05)
    assert _call(base + "/engineer", {"address": "Fast St & Quick Ave"}) == (200, {"junction": {"name": "Fast St & Quick Ave"}})
    assert _call(base + "/engineer", {"address": "Nowhere Rd & Lost Ln"}) == (422, {"error": "could not find that place"})
    code, body = _call(base + "/engineer", {"address": "Slow St & Long Ave"})
    assert code == 202 and len(body["job"]) == 16
    assert _call(f"{base}/engineer/{body['job']}")[1]["status"] == "running"
    slow.set()
    for _ in range(100):
        rec = _call(f"{base}/engineer/{body['job']}")[1]
        if rec["status"] != "running":
            break
        time.sleep(0.05)
    assert rec["status"] == "done" and rec["result"]["junction"]["name"] == "Slow St & Long Ave"


def test_review_endpoints_end_to_end(monkeypatch, tmp_path):
    from nearmisslens import review
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(check, "supported", lambda city: ({"id": city}, None) if city == "zz" else (None, "no crash data"))
    monkeypatch.setattr(review, "review", lambda text, city, *a, **k: {"status": "published", "verdict": "proceed",
                                                                       "cost_usd": {"meta": 0.03, "open_weights_red_team": 0.01}})
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _call(base + "/cities")
            break
        except OSError:
            time.sleep(0.05)
    assert _call(base + "/review", {"proposal": "LPI at A St & B Ave, $10,000", "city": "la"})[0] == 422
    assert _call(base + "/review", {"proposal": "short", "city": "zz"})[0] == 400
    code, body = _call(base + "/review", {"proposal": "LPI at A St & B Ave, $10,000", "city": "zz"})
    assert code == 202
    for _ in range(100):
        code, rec = _call(f"{base}/review/{body['job']}")
        if rec["status"] != "running":
            break
        time.sleep(0.05)
    assert rec["status"] == "done" and rec["result"]["verdict"] == "proceed"


def test_portfolio_endpoints_end_to_end(monkeypatch, tmp_path):
    from nearmisslens import review
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(check, "supported", lambda city: ({"id": city}, None) if city == "zz" else (None, "no crash data"))

    def fake(text, city, *a, **k):
        return {"status": "published", "verdict": "proceed", "corner": text[:20], "proposal": {"cost_usd": 10000},
                "appraisal": {"verdict": "proceed", "parts": [{"countermeasure": "A", "verdict": "proceed",
                                                               "proposed": {"injury_crashes_avoided_per_year": 0.2}}]},
                "cost_usd": {"meta": 0.03, "open_weights_red_team": 0.01}}
    monkeypatch.setattr(review, "review", fake)
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _call(base + "/cities")
            break
        except OSError:
            time.sleep(0.05)
    two = "Beacons at A St & B Ave\nAn island at C St & D Ave"
    assert _call(base + "/portfolio", {"proposals": "only one proposal here", "city": "zz"})[0] == 400
    assert _call(base + "/portfolio", {"proposals": "\n".join(["Beacons at A St & B Ave"] * 9), "city": "zz"})[0] == 400
    assert _call(base + "/portfolio", {"proposals": two, "city": "la"})[0] == 422
    assert _call(base + "/portfolio", {"proposals": two, "city": "zz", "budget_total": "lots"})[0] == 400
    code, body = _call(base + "/portfolio", {"proposals": two, "city": "zz", "budget_total": 15000})
    assert code == 202
    for _ in range(200):
        code, rec = _call(f"{base}/portfolio/{body['job']}")
        if rec["status"] != "running":
            break
        time.sleep(0.05)
    res = rec["result"]
    assert rec["status"] == "done" and res["totals"]["build"] == 2 and len(res["budget_plan"]["chosen"]) == 1
    assert "Within a budget of $15,000" in res["markdown"]


def test_the_static_copy_may_call_the_endpoints_and_no_one_else(monkeypatch, tmp_path):
    """The GitHub Pages copy is another origin: its forms need CORS, and only listed origins get it."""
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    monkeypatch.setattr(app, "ALLOWED_ORIGINS", {"https://pages.example"})
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            _call(base + "/cities")
            break
        except OSError:
            time.sleep(0.05)

    def opts(origin):
        req = urllib.request.Request(base + "/review", method="OPTIONS", headers={"Origin": origin})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)
    code, h = opts("https://pages.example")
    assert code == 204 and h["Access-Control-Allow-Origin"] == "https://pages.example" and "POST" in h["Access-Control-Allow-Methods"]
    code, h = opts("https://evil.example")
    assert code == 403 and "Access-Control-Allow-Origin" not in h
    req = urllib.request.Request(base + "/cities", headers={"Origin": "https://pages.example"})
    with urllib.request.urlopen(req) as r:
        assert r.headers["Access-Control-Allow-Origin"] == "https://pages.example"


def test_health_says_the_server_is_up_and_what_it_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(app.SETTINGS, "runs_dir", tmp_path, raising=False)
    port = _port()
    threading.Thread(target=app.serve, kwargs={"port": port, "open_weights": False}, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            code, d = _call(base + "/health")
            break
        except OSError:
            time.sleep(0.05)
    assert code == 200 and d["ok"] is True and d["version"] and d["records_as_of"]
    req = urllib.request.Request(base + "/health")
    with urllib.request.urlopen(req) as r:
        assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Referrer-Policy"] == "no-referrer"


def test_one_visitor_cannot_use_up_the_day():
    """A visitor may start a few paid jobs an hour; others are not affected; the window rolls; nothing is kept as an
    address (only salted hashes, dropped after the window)."""
    from nearmisslens.budget import VisitorLimit
    lim = VisitorLimit(jobs=2, window_s=100)
    assert lim.allow("1.2.3.4", now=0) == (True, 0)
    assert lim.allow("1.2.3.4", now=10) == (True, 0)
    ok, wait = lim.allow("1.2.3.4", now=20)
    assert not ok and wait == 81
    assert lim.allow("5.6.7.8", now=20) == (True, 0)
    assert lim.allow("1.2.3.4", now=101)[0]
    assert not any("1.2.3.4" in k for k in lim._seen)
    lim.allow("9.9.9.9", now=500)
    assert len(lim._seen) == 1
