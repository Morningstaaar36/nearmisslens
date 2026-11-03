"""A busy Overpass server is followed at once by a mirror, not after a back-off; back-off comes only before a server
is asked again."""
from nearmisslens import context


def test_mirrors_are_tried_without_sleeping_and_a_repeat_backs_off(monkeypatch, tmp_path):
    monkeypatch.setattr(context.SETTINGS, "cache_dir", tmp_path, raising=False)
    monkeypatch.setattr(context.SETTINGS, "replay", False, raising=False)
    asked, slept = [], []

    def get(url, params, data, timeout, total=None):
        asked.append(url)
        return (504, b"") if len(asked) < 4 else (200, b'{"elements": []}')

    monkeypatch.setattr(context, "_get", get)
    monkeypatch.setattr(context.time, "sleep", lambda s: slept.append(s))
    out, _ = context.fetch(context.OVERPASS, data={"data": "q"}, attempts=5)
    assert out == {"elements": []}
    assert asked[:3] == [context.OVERPASS, *context.OVERPASS_MIRRORS] and len(asked) == 4
    assert len(slept) == 1  # only before the main server was asked a second time


def test_a_server_that_trickles_its_answer_is_cut_at_the_whole_request_deadline(monkeypatch):
    import pytest

    class R:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_bytes(self):
            while True:
                yield b" "

    class C:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, *a, **k): return R()

    clock = iter(range(0, 10**6))
    monkeypatch.setattr(context.httpx, "Client", C)
    monkeypatch.setattr(context.time, "time", lambda: next(clock))
    with pytest.raises(context.httpx.ReadTimeout):
        context._get("https://example.org", None, None, timeout=30)
