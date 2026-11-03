"""Takes recorded elsewhere (an iPad's Voice Memos) become the demo's takes, matched by line number and scene."""
import shutil
import subprocess

import pytest

from nearmisslens import demo_desk, voicestudio
from nearmisslens.demo_copilot import Scene


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_recordings_named_by_line_become_takes(tmp_path, monkeypatch):
    lines = [Scene("open", "First line.", "card"), Scene("memo", "Second line.", "page"), Scene("close", "Last.", "card")]
    monkeypatch.setattr(demo_desk, "script", lambda f=None: lines)
    monkeypatch.setattr(voicestudio, "voice_dir", lambda: tmp_path / "voice")
    (tmp_path / "voice").mkdir()
    rec = tmp_path / "rec"
    rec.mkdir()
    for name in ("01_open.m4a", "Memo.m4a"):  # by number and scene, or the scene alone
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", "-c:a", "aac",
                        str(rec / name)], check=True)
    out = voicestudio.import_takes(rec)
    assert out == {"imported": {"open": "01_open.m4a", "memo": "Memo.m4a"}, "missing": ["03_close"]}
    assert voicestudio.take(0, "open", "First line.") is not None
    assert voicestudio.take(0, "open", "A changed line.") is None  # a take belongs to its line's exact text
    assert "## 03_close" in voicestudio.script_md()
