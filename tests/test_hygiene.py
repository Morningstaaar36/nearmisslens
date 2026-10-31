import subprocess
from pathlib import Path

import pytest

from nearmisslens import config
from nearmisslens.config import portable, resolve

ROOT = Path(__file__).resolve().parent.parent


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        pytest.skip("not a git checkout")
    return [ROOT / f for f in out.stdout.split()]


def test_no_machine_paths_in_tracked_files():
    home = str(Path.home())
    bad = [str(p.relative_to(ROOT)) for p in _tracked()
           if p.suffix in (".json", ".csv", ".md", ".py", ".html", ".js") and p.exists()
           and home in p.read_text(errors="ignore")]
    assert not bad, bad


def test_portable_paths_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config.SETTINGS, "runs_dir", tmp_path / "runs")
    p = tmp_path / "runs" / "briefs" / "a" / "fix.jpg"
    assert portable(str(p)) == "$RUNS/briefs/a/fix.jpg"
    assert resolve("$RUNS/briefs/a/fix.jpg") == p
    assert resolve("/etc/hosts") == Path("/etc/hosts")


def test_open_weights_runs_are_priced_at_the_servers_rates(tmp_path):
    from nearmisslens.agent import Tool, run_agent
    from nearmisslens.openclient import PRICE

    class Client:
        def __init__(self):
            self.price = PRICE
        usd = __import__("nearmisslens.openclient", fromlist=["x"]).OpenWeightsClient.usd

        def cached(self, namespace, request, run, cost_fn, estimate, what, require_text=False, complete=None):
            r = run()
            self.last = cost_fn(r)
            return r

        def create_response(self, payload):
            return {"id": "r", "output": [{"type": "function_call", "name": "finish", "arguments": "{}", "call_id": "c"}],
                    "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}

    c = Client()
    run_agent(c, "muse-spark-1.3-contributor", "i", "t",
              [Tool("finish", "f", {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                    lambda: {"ok": True})], 2, 100.0)
    assert abs(c.last[0] - PRICE["input"]) < 1e-9


def test_panel_ablation_records_errors_and_keeps_the_first_submission():
    from nearmisslens import panel
    from nearmisslens.agent import Tool
    from tests.test_agent import FakeClient, call, usage
    role = next(iter(panel.BUDGET_USD))
    finish = Tool("finish", "f", panel._obj({"memo": {"type": "string"}}, ["memo"]),
                  panel._finish(lambda **k: ["number 99 is not in the facts"], checked=False))
    fc = FakeClient([{"id": "r1", "output": [call("finish", {"memo": "99 crashes"}, "c1")], "usage": usage()}])
    out = panel._stage(fc, "muse-spark-1.3-contributor", "i", "t", [], finish, role, "test", checked=False)
    assert out["accepted"] and out["ungrounded"] == ["number 99 is not in the facts"]


def test_docs_never_say_judge():
    import subprocess
    from nearmisslens.config import ROOT
    word = "jud" + "ge"
    paths = ["README.md", "FEATURES.md", "docs", "validation/BENCH.md", "validation/RESULTS.md", "validation/PREREG.md",
             "validation/BENCH_PREREG.md", "PRIVACY.md", "LICENSES.md"]
    found = subprocess.run(["git", "grep", "-n", "-i", word[:4], "--", *[p for p in paths if (ROOT / p).exists()]],
                           cwd=ROOT, capture_output=True, text=True).stdout
    assert found == "", found[:500]


def test_pinned_asof_makes_crash_queries_independent_of_today(monkeypatch):
    import datetime as dt
    from nearmisslens import config, context, opendata
    seen = []
    monkeypatch.setattr(context, "fetch", lambda url, params=None, **k: (seen.append(params) or [], 0))
    a = {"id": "x", "platform": "socrata", "endpoint": "https://e", "geo_field": "loc", "date_field": "d"}
    monkeypatch.setenv("NML_ASOF", "2026-10-31")
    for _ in range(2):  # the query depends only on the pinned date, never on today
        opendata.rows_near(a, 40.0, -73.0, 100, config.since(5))
    assert seen[0] == seen[1] and "'2026-11-01'" in seen[0]["$where"] and "'2021-10-31'" in seen[0]["$where"]
    assert config.since(5) == dt.date(2021, 10, 31)


def test_readme_corner_geocodes_offline(monkeypatch):
    from nearmisslens import brief, config
    monkeypatch.setattr(config.SETTINGS, "replay", True)
    lat, lon, name = brief.geocode("Bruckner Boulevard & Hunts Point Avenue, Bronx, NY")
    assert abs(lat - 40.8202) < 0.002 and abs(lon + 73.8906) < 0.002
