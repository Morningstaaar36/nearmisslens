import pytest

from nearmisslens import app, pages
from nearmisslens.budget import DailyBudget


def test_bad_bodies_are_400_not_crashes():
    for raw in (b"{not json", b"[1,2]", b'"text"'):
        with pytest.raises(app.BadRequest):
            app.parse(raw)
    assert app.parse(b"") == {}
    for q in ({}, {"address": 7}, {"address": "x"}, {"address": "a" * 200}, {"address": "bad\x00char"}):
        with pytest.raises(app.BadRequest):
            app.address(q)
    assert app.address({"address": "  Main St & Oak Ave  "}) == "Main St & Oak Ave"


def test_points_must_be_numbers_inside_a_registered_city(monkeypatch):
    monkeypatch.setattr(app.context, "city_of", lambda lat, lon: None)
    for q in ({"name": "A & B", "lat": "1", "lon": 2}, {"name": "A & B", "lat": float("nan"), "lon": 2},
              {"name": "A & B", "lat": True, "lon": 2}, {"name": "A & B", "lat": 1.0, "lon": 2.0}):
        with pytest.raises(app.BadRequest):
            app.point(q)
    monkeypatch.setattr(app.context, "city_of", lambda lat, lon: "t")
    assert app.point({"name": "A & B", "lat": 1, "lon": 2}) == ("A & B", 1.0, 2.0)


def test_static_files_never_leave_docs_or_serve_the_video_viewer():
    assert app.static_file("/data/../../pyproject.toml") is None
    assert app.static_file("/data/%2e%2e/%2e%2e/README.md") is None
    assert app.static_file("/../nearmisslens/config.py") is None
    assert app.static_file("/data/does-not-exist.json") is None


def test_budget_caps_requests_and_dollars_and_settles(tmp_path):
    b = DailyBudget(usd=0.05, requests=2, path=tmp_path / "b.json")
    assert b.request() and b.request() and not b.request()
    assert b.reserve(0.03) and not b.reserve(0.03)
    b.settle(0.03, 0.01)
    assert b.reserve(0.03) and b.state()["usd"] == pytest.approx(0.04)
    assert "ip" not in b.path.read_text().lower()


def test_site_check_finds_machine_paths_and_keys(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "index.html").write_text("<p>ok</p>")
    (tmp_path / "copilot.js").write_text("ok")
    (tmp_path / "data" / "a.json").write_text('{"p": "/home/someone/x"}')
    (tmp_path / "data" / "b.json").write_text('{"api_key": "abcdefghijkl"}')
    got = pages.check(tmp_path)
    assert any("machine path" in g for g in got) and any("key" in g for g in got)


def test_live_endpoint_must_be_https():
    with pytest.raises(ValueError):
        pages.page("static", "http://example.com")
    assert 'content="static"' in pages.page("static")
