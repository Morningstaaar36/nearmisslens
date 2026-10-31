import io
import json
import struct
import zipfile

import httpx
import pandas as pd
import pytest

from nearmisslens import agent, fetch, panel, runner
from nearmisslens.config import Settings
from nearmisslens.cost import BudgetExceeded
from nearmisslens.meta_client import IncompleteResponse, MetaClient
from tests.test_agent import FakeClient, call, usage
from tests.test_panel import MEMO, cmf_db, facts, reply


def test_panel_keeps_the_accepted_submission_when_a_bad_one_follows_in_the_same_turn():
    good = {"recommendations": [{"rank": 1, "crfid": "1447", "reason": "12 crossing conflicts"}]}
    bad = {"recommendations": [{"rank": 1, "crfid": "4096", "reason": "x"}]}
    both = {"id": "p1", "output": [call("finish", good, "a"), call("finish", bad, "b")], "usage": usage()}
    fc = FakeClient([both, reply("s1", "finish", {"objections": []}),
                     reply("j1", "finish", {"decisions": [{"rank": 1, "crfid": "1447", "accept": True, "reason": "ok"}],
                                            "memo": "Hotspot 1: CMF 1447."})])
    result = panel.run_panel(fc, facts(), MEMO, cmf_db(), "t")
    assert result["status"] == "complete" and result["proposals"][0]["crfid"] == "1447"


def test_road_user_ids_are_not_read_as_cmf_ids():
    g = panel.Grounding(facts(), MEMO)
    assert not any("CMF" in e for e in g.text("road user ID 4096 crossed"))
    assert any("CMF 9999" in e for e in g.text("CMF 9999 applies"))


def test_incomplete_model_turn_stops_the_agent_cleanly():
    class Truncating(FakeClient):
        def cached(self, *a, **k):
            raise IncompleteResponse("status='incomplete'")
    run = agent.run_agent(Truncating([]), "m", "i", "t", [], max_turns=3, budget_usd=1.0)
    assert run.stopped.startswith("incomplete") and run.turns == 1


def test_budget_is_not_checked_in_replay(tmp_path):
    led = tmp_path / "runs"
    led.mkdir()
    (led / "ledger.jsonl").write_text(json.dumps({"model": "m", "usd": 59.99, "what": "x"}) + "\n")
    live = MetaClient(Settings(cache_dir=tmp_path / "c", runs_dir=led, budget_usd=60.0))
    with pytest.raises(BudgetExceeded):
        live.check_budget(1.0, "run")
    replay = MetaClient(Settings(cache_dir=tmp_path / "c", runs_dir=led, budget_usd=60.0, replay=True))
    replay.check_budget(1.0, "run")


def _has_fluid() -> bool:
    from nearmisslens import fluid
    return fluid.clip(*fluid.DEV).video.exists()


@pytest.mark.skipif(not _has_fluid(), reason="needs the FLUID dev video (nml fetch)")
def test_sam_states_never_track(monkeypatch):
    def no_tracking(*a, **k):
        assert k.get("cached_only") is True
        raise FileNotFoundError("no SAM 3.1 tracks")
    monkeypatch.setattr(runner.pipeline, "track_api", no_tracking)
    monkeypatch.setattr(runner.pipeline, "calibration_for", lambda c: None)
    with pytest.raises(FileNotFoundError):
        runner.site_states("dev", "sam", client=object())


def test_severity_at_matched_recall():
    ref = pd.DataFrame({"t": [1.0, 5.0], "cls_1": ["vehicle"] * 2, "cls_2": ["vehicle"] * 2})
    cand = pd.DataFrame({"t": [1.0, 9.0, 5.0], "cls_1": ["vehicle"] * 3, "cls_2": ["vehicle"] * 3,
                         "value": [0.2, 0.3, 0.9]})
    s = runner.severity_at_recall(cand, ref, 1.0)
    assert s["kept"] == 3 and s["recall"] == 1.0
    assert runner.severity_at_recall(cand, ref, 0.5)["kept"] == 1


def test_zip64_extra_with_disk_number_parses(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.bin", b"abc" * 30000)
    data = bytearray(buf.getvalue())
    cd = data.rfind(b"PK\x01\x02")
    nlen, elen = struct.unpack("<HH", data[cd + 28:cd + 32])
    assert elen == 0
    off = struct.unpack("<I", data[cd + 42:cd + 46])[0]
    extra = struct.pack("<HHQI", 1, 12, off, 0)
    data[cd + 42:cd + 46] = struct.pack("<I", 0xFFFFFFFF)
    data[cd + 30:cd + 32] = struct.pack("<H", len(extra))
    name_end = cd + 46 + nlen
    data[name_end:name_end] = extra
    e = data.rfind(b"PK\x05\x06")
    size, start = struct.unpack("<II", data[e + 12:e + 20])
    data[e + 12:e + 16] = struct.pack("<I", size + len(extra))
    blob = bytes(data)

    def handler(request):
        a, b = request.headers["range"].removeprefix("bytes=").split("-")
        a, b = int(a), min(int(b), len(blob) - 1)
        return httpx.Response(206, content=blob[a:b + 1], headers={"content-range": f"bytes {a}-{b}/{len(blob)}"})
    monkeypatch.setattr(fetch, "_client", lambda verify=True: httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetch.central_directory("https://x/z")["a.bin"]["offset"] == off


def test_interrupted_member_download_keeps_the_partial_file(monkeypatch, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("v.mp4"), b"x" * 200000, compress_type=zipfile.ZIP_STORED)
    blob = buf.getvalue()

    def handler(request):
        a, b = request.headers["range"].removeprefix("bytes=").split("-")
        a, b = int(a), min(int(b), len(blob) - 1)
        if a < len(blob) - 70000 and b - a > 60000:
            b = a + 999
        return httpx.Response(206, content=blob[a:b + 1], headers={"content-range": f"bytes {a}-{b}/{len(blob)}"})
    monkeypatch.setattr(fetch, "_client", lambda verify=True: httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError, match="incomplete"):
        fetch.fetch_member("https://x/z", "v.mp4", tmp_path / "v.mp4")
    assert (tmp_path / ".v.mp4.part").stat().st_size == 8000 and not (tmp_path / "v.mp4").exists()
