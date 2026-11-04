"""The README's no-key example runs on a fresh clone: the committed starter pack (replay/) holds every public-data
answer it reads, so --replay needs no download, key or network."""
import gzip
import json

from nearmisslens import context, engineer, packcache
from nearmisslens.config import SETTINGS, asof


def test_the_readme_example_runs_from_the_committed_pack_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(SETTINGS, "replay", True, raising=False)
    monkeypatch.setattr(SETTINGS, "cache_dir", tmp_path / "empty_cache", raising=False)  # nothing downloaded
    monkeypatch.setattr(SETTINGS, "runs_dir", tmp_path / "runs", raising=False)
    for q in packcache.starter_queries():
        rep = engineer.plan(q)
        assert not rep["claim_errors"]
        crashes = rep["findings"]["choose_fixes"]["crashes"]
        assert crashes["injury_crashes"] > 0 and crashes["asof"] == asof().isoformat()  # the pinned records date


def test_the_pack_holds_no_key_or_contact_detail():
    files = sorted(context.STARTER_DIR.glob("*.json.gz"))
    assert files and sum(p.stat().st_size for p in files) < 5e6
    for p in files:
        raw = gzip.decompress(p.read_bytes())
        assert not packcache.KEYISH.search(raw), p.name
        assert packcache.scrub(json.loads(raw)) == json.loads(raw), p.name


def test_live_runs_never_read_the_pack(monkeypatch):
    monkeypatch.setattr(SETTINGS, "replay", False, raising=False)
    key = next(context.STARTER_DIR.glob("*.json.gz")).name.split(".")[0]
    assert context._starter(key) is None
