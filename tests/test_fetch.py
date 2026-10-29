import io
import zipfile

import httpx
import pytest

from nearmisslens import fetch


def archive() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("video/a.mp4"), b"stored-bytes" * 20000, compress_type=zipfile.ZIP_STORED)
        z.writestr("video/b.mp4", b"deflated " * 9000, compress_type=zipfile.ZIP_DEFLATED)
        with z.open("c.bin", "w", force_zip64=True) as f:
            f.write(b"z" * 1000)
    return buf.getvalue()


@pytest.fixture
def served(monkeypatch):
    blob = {"data": archive(), "fail_once": True}

    def handler(request):
        start, end = request.headers["range"].removeprefix("bytes=").split("-")
        start, end = int(start), min(int(end), len(blob["data"]) - 1)
        body = blob["data"][start:end + 1]
        if blob["fail_once"] and start < 1000 and len(body) > 50_000:
            blob["fail_once"] = False
            body = body[:20_000]
            return httpx.Response(206, content=body, headers={"content-range": f"bytes {start}-{start + 19_999}/{len(blob['data'])}"})
        return httpx.Response(206, content=body, headers={"content-range": f"bytes {start}-{end}/{len(blob['data'])}"})

    monkeypatch.setattr(fetch, "_client", lambda verify=True: httpx.Client(transport=httpx.MockTransport(handler)))
    return blob


def test_central_directory_lists_members_with_zip64(served):
    cd = fetch.central_directory("https://x/z")
    assert set(cd) == {"video/a.mp4", "video/b.mp4", "c.bin"}
    assert cd["video/a.mp4"]["method"] == 0 and cd["video/b.mp4"]["method"] == 8


def test_fetch_member_resumes_and_checks_crc(served, tmp_path):
    a = fetch.fetch_member("https://x/z", "video/a.mp4", tmp_path / "a.mp4")
    assert a.read_bytes() == b"stored-bytes" * 20000 and not served["fail_once"]
    b = fetch.fetch_member("https://x/z", "video/b.mp4", tmp_path / "b.mp4")
    assert b.read_bytes() == b"deflated " * 9000
    assert not list(tmp_path.glob(".*"))
