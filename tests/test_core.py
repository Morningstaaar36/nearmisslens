import pytest

from nearmisslens.cache import Cache, ReplayMiss, request_key
from nearmisslens.cost import BudgetExceeded, CostMeter, sam_video_usd, token_usd, voice_usd


def test_prices():
    assert sam_video_usd(10) == pytest.approx(0.01)
    assert sam_video_usd(600) == pytest.approx(0.12)
    assert token_usd("muse-spark-1.3", 1_000_000, 0) == pytest.approx(1.25)
    assert token_usd("muse-spark-1.3-contributor", 0, 1_000_000) == pytest.approx(0.20)
    assert voice_usd(3600.9) == pytest.approx(0.18)


def test_meter_cap(tmp_path):
    m = CostMeter(tmp_path / "ledger.jsonl", cap_usd=1.0)
    m.record("sam-3.1", 0.6, "a")
    m.check(0.3, "b")
    with pytest.raises(BudgetExceeded):
        m.check(0.5, "c")
    assert m.summary()["by_model"] == {"sam-3.1": 0.6}


def test_cache_roundtrip_and_replay(tmp_path):
    key = request_key("ns", {"a": 1})
    c = Cache(tmp_path)
    assert c.get("ns", key) is None
    c.put("ns", key, {"x": [1, 2]})
    assert c.get("ns", key) == {"x": [1, 2]}
    with pytest.raises(ReplayMiss):
        Cache(tmp_path, replay=True).get("ns", request_key("ns", {"a": 2}))
