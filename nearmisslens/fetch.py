"""Download the data the pipeline uses: FLUID (figshare 10.6084/m9.figshare.29974954 v2, CC BY 4.0) derived data
for the two sites, the three registered video clips read out of the multi-gigabyte video archives with HTTP range
requests, and the FHWA CMF Clearinghouse table. Archives are checked against figshare's MD5 and clips against their
ZIP CRC32."""
from __future__ import annotations

import hashlib
import re
import ssl
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import fluid
from .config import SETTINGS
from .countermeasures import CMF_PATH, CMF_URL

FIGSHARE = "https://ndownloader.figshare.com/files/"
SITES = {
    "FIDRT": {"derived": ("64179082", "103191b9f67d4d4862b0791832ff3f95"), "videos": "57459310"},
    "FI": {"derived": ("64179085", "69183542c475d9e759306bf8a1b0737d"), "videos": "61923796"},
    "TI": {"derived": ("64179079", "fc2870464b3509130ce606c4f43a492b"), "videos": "57423067"},
}
CLIPS = (fluid.DEV, fluid.TEST, fluid.HELDOUT)


def _client(verify=True) -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120.0, connect=30.0), verify=verify)


def _range(url: str, start: int, end: int) -> bytes:
    with _client() as c:
        r = c.get(url, headers={"Range": f"bytes={start}-{end}"})
        if r.status_code != 206:
            raise RuntimeError(f"{url}: range request returned HTTP {r.status_code}")
        return r.content


def _size(url: str) -> int:
    with _client() as c:
        r = c.get(url, headers={"Range": "bytes=0-0"})
        return int(r.headers["content-range"].rsplit("/", 1)[1])


def central_directory(url: str) -> dict[str, dict]:
    """Members of a remote ZIP (ZIP64 aware): name -> method, crc, compressed size and local header offset."""
    size = _size(url)
    tail = _range(url, max(0, size - 65_557), size - 1)
    e = tail.rfind(b"PK\x05\x06")
    if e < 0:
        raise ValueError(f"{url}: no end-of-central-directory record")
    cd_size, cd_off = struct.unpack("<II", tail[e + 12:e + 20])
    loc = tail.rfind(b"PK\x06\x07", 0, e)
    if loc >= 0:
        z64 = struct.unpack("<Q", tail[loc + 8:loc + 16])[0]
        rec = _range(url, z64, z64 + 55)
        cd_size, cd_off = struct.unpack("<QQ", rec[40:56])
    cd = _range(url, cd_off, cd_off + cd_size - 1)
    out, i = {}, 0
    while cd[i:i + 4] == b"PK\x01\x02":
        method, = struct.unpack("<H", cd[i + 10:i + 12])
        crc, csize, usize = struct.unpack("<III", cd[i + 16:i + 28])
        nlen, elen, clen = struct.unpack("<HHH", cd[i + 28:i + 34])
        off, = struct.unpack("<I", cd[i + 42:i + 46])
        name = cd[i + 46:i + 46 + nlen].decode()
        extra = cd[i + 46 + nlen:i + 46 + nlen + elen]
        j = 0
        while j + 4 <= len(extra):
            tag, ln = struct.unpack("<HH", extra[j:j + 4])
            if tag == 1:
                pos = j + 4

                def take() -> int:
                    nonlocal pos
                    pos += 8
                    return struct.unpack("<Q", extra[pos - 8:pos])[0]

                if usize == 0xFFFFFFFF:
                    usize = take()
                if csize == 0xFFFFFFFF:
                    csize = take()
                if off == 0xFFFFFFFF:
                    off = take()
            j += 4 + ln
        out[name] = {"method": method, "crc": crc, "csize": csize, "usize": usize, "offset": off}
        i += 46 + nlen + elen + clen
    return out


def fetch_member(url: str, member: str, out: Path) -> Path:
    """One file out of a remote ZIP, resumable, verified by CRC32."""
    out = Path(out)
    if out.exists():
        return out
    m = central_directory(url)[member]
    if m["method"] not in (0, 8):
        raise ValueError(f"{member}: unsupported compression method {m['method']}")
    head = _range(url, m["offset"], m["offset"] + 29)
    nlen, elen = struct.unpack("<HH", head[26:30])
    start = m["offset"] + 30 + nlen + elen
    end = start + m["csize"] - 1
    part = out.with_name(f".{out.name}.part")
    out.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(8):
        done = part.stat().st_size if part.exists() else 0
        if done >= m["csize"]:
            break
        try:
            with _client() as c, c.stream("GET", url, headers={"Range": f"bytes={start + done}-{end}"}) as r, \
                    part.open("ab") as f:
                if r.status_code != 206:
                    raise RuntimeError(f"HTTP {r.status_code}")
                for k, chunk in enumerate(r.iter_bytes(1 << 20)):
                    f.write(chunk)
                    if k % 200 == 0:
                        print(f"{out.name}: {(done + f.tell()) / 1e6:.0f} / {m['csize'] / 1e6:.0f} MB", flush=True)
        except (httpx.TransportError, RuntimeError) as err:
            print(f"{out.name}: retrying after {err}")
    if not part.exists() or part.stat().st_size < m["csize"]:
        raise RuntimeError(f"{member}: download incomplete; the partial file is kept, run again to resume")
    crc, inflate = 0, zlib.decompressobj(-15) if m["method"] == 8 else None
    tmp = out.with_name(f".{out.name}.tmp")
    with part.open("rb") as src, tmp.open("wb") as dst:
        for block in iter(lambda: src.read(1 << 22), b""):
            data = inflate.decompress(block) if inflate else block
            crc = zlib.crc32(data, crc)
            dst.write(data)
        if inflate:
            tail = inflate.flush()
            crc = zlib.crc32(tail, crc)
            dst.write(tail)
    if crc != m["crc"]:
        tmp.unlink()
        part.unlink()
        raise ValueError(f"{member}: CRC32 mismatch; partial download removed, run again")
    tmp.replace(out)
    part.unlink()
    return out


def download(url: str, out: Path, md5: str | None = None, verify=True) -> Path:
    out = Path(out)
    if out.exists() and (md5 is None or _md5(out) == md5):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.part")
    with _client(verify) as c, c.stream("GET", url) as r, tmp.open("wb") as f:
        r.raise_for_status()
        for chunk in r.iter_bytes(1 << 20):
            f.write(chunk)
    if md5 and _md5(tmp) != md5:
        tmp.unlink()
        raise ValueError(f"{out.name}: MD5 mismatch")
    tmp.replace(out)
    return out


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def issuer_bundle(url: str) -> str:
    """A CA bundle with the server's issuing certificate added, for servers that omit it from their chain. The
    issuer is fetched from the Authority Information Access URL in the server's own certificate."""
    import certifi
    host = urlparse(url).hostname
    der = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate((host, 443)))
    aia = re.search(rb"http://[\x21-\x7e]+?\.(?:crt|cer|der)", der)
    if not aia:
        raise RuntimeError(f"{host}: certificate chain is incomplete and names no issuer URL")
    with _client() as c:
        issuer = c.get(aia.group().decode()).content
    pem = issuer.decode() if issuer.startswith(b"-----BEGIN") else ssl.DER_cert_to_PEM_cert(issuer)
    bundle = Path(tempfile.gettempdir()) / f"nml_{host}_bundle.pem"
    bundle.write_text(Path(certifi.where()).read_text() + "\n" + pem)
    return str(bundle)


def fetch_cmf(out: Path = CMF_PATH) -> Path:
    if out.exists():
        return out
    try:
        return download(CMF_URL, out)
    except httpx.ConnectError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        return download(CMF_URL, out, verify=issuer_bundle(CMF_URL))


def fetch_all(data_dir: Path | None = None, clips=CLIPS) -> list[Path]:
    """Derived data for every site, the given clips' videos (default: the registered splits) and the CMF table.
    clips=fluid.FLIGHTS fetches all 14 flights (about 19 GB) for NML-Bench."""
    base = Path(data_dir or SETTINGS.data_dir) / "fluid"
    done = []
    for site, src in SITES.items():
        if not (base / site / "derived_data").exists():
            fid, md5 = src["derived"]
            z = download(FIGSHARE + fid, base / f"{site}_derived_data.zip", md5)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(base / site)
        done.append(base / site / "derived_data")
    for site, stem in clips:
        c = fluid.clip(site, stem, Path(data_dir or SETTINGS.data_dir))
        if not c.video.exists():
            url = FIGSHARE + SITES[site]["videos"]
            names = central_directory(url)
            member = next(n for n in names if n.rsplit("/", 1)[-1] == f"{stem}.mp4")
            fetch_member(url, member, c.video)
        done.append(c.video)
    done.append(fetch_cmf())
    return done
