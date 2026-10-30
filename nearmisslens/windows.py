"""Registered one-minute windows of FLUID flights (PREREG change 11), cut straight out of the remote ZIP archives:
ffmpeg reads only the byte range it needs, so a window costs seconds instead of a 1–3 GB download. Window frame 0 is
original frame 1200 (0-based), which the pipeline numbers 1201; this was checked against a local video by PSNR."""
from __future__ import annotations

import struct
import subprocess
from pathlib import Path

from . import fluid
from .config import SETTINGS
from .fetch import FIGSHARE, SITES, _range, central_directory

START_S, DURATION_S = 120.0, 60.0
FRESH = tuple(f for f in fluid.FLIGHTS if f not in (fluid.DEV, fluid.TEST, fluid.HELDOUT))


def window_path(site: str, stem: str, data_dir: Path | None = None) -> Path:
    return Path(data_dir or SETTINGS.data_dir) / "fluid" / "windows" / f"{site}_{stem}_w{START_S:.0f}.mp4"


def member_range(site: str, stem: str) -> tuple[str, int, int]:
    url = FIGSHARE + SITES[site]["videos"]
    cd = central_directory(url)
    name = next(n for n in cd if n.rsplit("/", 1)[-1] == f"{stem}.mp4")
    m = cd[name]
    if m["method"] != 0:
        raise ValueError(f"{name} is compressed; a byte-range window needs a stored member")
    nlen, elen = struct.unpack("<HH", _range(url, m["offset"], m["offset"] + 29)[26:30])
    start = m["offset"] + 30 + nlen + elen
    return url, start, start + m["csize"]


def cut(site: str, stem: str) -> Path:
    """The registered window as an H.264 file (CRF 14), from the remote archive."""
    out = window_path(site, stem)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    local = fluid.clip(site, stem).video
    if local.exists():  # a fully downloaded flight (members stored compressed cannot be read by byte range)
        src = str(local)
    else:
        url, start, end = member_range(site, stem)
        src = f"subfile,,start,{start},end,{end},,:{url}"
    tmp = out.with_name(f".{out.name}.tmp.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-protocol_whitelist", "subfile,https,http,tcp,tls,file",
                    "-ss", f"{START_S}", "-i", src, "-t", f"{DURATION_S}",
                    "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
                    str(tmp)], check=True)
    tmp.replace(out)
    return out


def window_clip(site: str, stem: str) -> fluid.Clip:
    """A Clip whose video is the window and whose derived data (trajectories, signals, map) are the flight's."""
    c = fluid.clip(site, stem)
    return fluid.Clip(site, stem, window_path(site, stem), c.root)


FRAME_OFFSET = int(round(START_S * 10))


CHUNK = 2 << 20


def _curl_range(url: str, start: int, end: int, out: Path, offset: int) -> bool:
    """Fetch bytes [start, end] into out at offset; abandon connections slower than 60 KB/s so a retry can land on a
    faster server."""
    tmp = out.with_name(f"{out.name}.{start}.chunk")
    r = subprocess.run(["curl", "-s", "-L", "-r", f"{start}-{end}", "--speed-limit", "60000", "--speed-time", "6",
                        "--max-time", "120", "-o", str(tmp), url])
    ok = r.returncode == 0 and tmp.exists() and tmp.stat().st_size == end - start + 1
    if ok:
        with open(out, "r+b") as f:
            f.seek(offset)
            f.write(tmp.read_bytes())
    tmp.unlink(missing_ok=True)
    return ok


def _fill(url: str, base: int, ranges: list[tuple[int, int]], sparse: Path, workers: int = 8) -> None:
    """Download member-relative byte ranges into the sparse local copy, in 2 MB chunks, retrying slow chunks."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [(a, min(a + CHUNK - 1, e)) for s, e in ranges for a in range(s, e + 1, CHUNK)]
    for attempt in range(20):
        if not todo:
            return
        with ThreadPoolExecutor(workers) as ex:
            ok = list(ex.map(lambda r: _curl_range(url, base + r[0], base + r[1], sparse, r[0]), todo))
        todo = [r for r, k in zip(todo, ok) if not k]
    if todo:
        raise RuntimeError(f"{len(todo)} chunks still missing after retries")


def _boxes(url: str, base: int, size: int) -> dict[str, tuple[int, int]]:
    """Top-level MP4 boxes of the member (offset, size), read from their 16-byte headers."""
    out, pos = {}, 0
    while pos < size:
        h = _range(url, base + pos, base + pos + 15)
        n, kind = struct.unpack(">I4s", h[:8])
        if n == 1:
            n = struct.unpack(">Q", h[8:16])[0]
        elif n == 0:
            n = size - pos
        out[kind.decode(errors="replace")] = (pos, n)
        pos += n
    return out


def cut_by_ranges(site: str, stem: str) -> Path:
    """The registered window from a stored member over a slow link: download the moov index, ask ffprobe which byte
    ranges hold the window from its preceding keyframe, fetch only those in parallel into a sparse local copy,
    then cut the window locally."""
    out = window_path(site, stem)
    if out.exists():
        return out
    url, start, end = member_range(site, stem)
    size = end - start
    sparse = out.with_name(f".{site}_{stem}.sparse.mp4")
    if not sparse.exists() or sparse.stat().st_size != size:
        with open(sparse, "wb") as f:
            f.truncate(size)
    boxes = _boxes(url, start, size)
    moov = boxes["moov"]
    _fill(url, start, [(0, 4095), (moov[0], moov[0] + moov[1] - 1)], sparse)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "packet=pts_time,size,pos,flags", "-of", "csv=p=0", str(sparse)], capture_output=True, text=True)
    packets = []
    for line in probe.stdout.splitlines():
        parts = line.split(",")
        if len(parts) < 4 or not parts[0] or parts[2] in ("", "N/A"):
            continue
        packets.append((float(parts[0]), int(parts[1]), int(parts[2]), "K" in parts[3]))
    # decoding starts at the last keyframe at or before the window (FLUID videos have one every 25 s)
    lo = max((t for t, _, _, key in packets if key and t <= START_S), default=0.0)
    hi = START_S + DURATION_S + 2.0
    spans = [(pos, pos + n - 1) for t, n, pos, _ in packets if lo <= t <= hi]
    if not spans:
        raise RuntimeError("no packets found in the window")
    _fill(url, start, [(min(a for a, _ in spans), max(b for _, b in spans))], sparse)
    tmp = out.with_name(f".{out.name}.tmp.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{START_S}", "-i", str(sparse), "-t", f"{DURATION_S}",
                    "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
                    str(tmp)], check=True)
    tmp.replace(out)
    sparse.unlink()
    return out


def fetch_compressed(site: str, stem: str) -> Path:
    """A deflate-compressed member downloaded in parallel chunks, inflated and CRC-checked locally."""
    import zlib
    from .fetch import central_directory as cdir
    c = fluid.clip(site, stem)
    if c.video.exists():
        return c.video
    url = FIGSHARE + SITES[site]["videos"]
    cd = cdir(url)
    name = next(n for n in cd if n.rsplit("/", 1)[-1] == f"{stem}.mp4")
    m = cd[name]
    nlen, elen = struct.unpack("<HH", _range(url, m["offset"], m["offset"] + 29)[26:30])
    start = m["offset"] + 30 + nlen + elen
    raw = c.video.with_name(f".{c.video.name}.deflate")
    if not raw.exists() or raw.stat().st_size != m["csize"]:
        with open(raw, "wb") as f:
            f.truncate(m["csize"])
    _fill(url, start, [(0, m["csize"] - 1)], raw, workers=12)
    inflate, crc = zlib.decompressobj(-15), 0
    tmp = c.video.with_name(f".{c.video.name}.tmp")
    with raw.open("rb") as src, tmp.open("wb") as dst:
        for block in iter(lambda: src.read(1 << 22), b""):
            data = inflate.decompress(block)
            crc = zlib.crc32(data, crc)
            dst.write(data)
        tail = inflate.flush()
        dst.write(tail)
        crc = zlib.crc32(tail, crc)
    if crc != m["crc"]:
        tmp.unlink()
        raise ValueError(f"{name}: CRC32 mismatch")
    tmp.replace(c.video)
    raw.unlink()
    return c.video


def smoke(site: str, stem: str) -> dict:
    """Free check of a cut window before any paid tracking: 600 decodable frames at 10 fps, and the calibration
    reprojects the reference pixel positions of those frames to their metric positions (median <= 0.6 m)."""
    import numpy as np
    from . import pipeline
    p = window_path(site, stem)
    pr = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                         "stream=nb_read_frames,r_frame_rate,width,height", "-of", "csv=p=0", str(p)],
                        capture_output=True, text=True).stdout.strip().split(",")
    wc = window_clip(site, stem)
    cal = pipeline.calibration_for(wc)
    t = fluid.load_trajectories(wc)
    t = t[t["frame"].between(FRAME_OFFSET + 1, FRAME_OFFSET + int(DURATION_S * 10))]
    err = np.linalg.norm(cal.to_metres(t[["cx", "cy"]].to_numpy()) - t[["cx_m", "cy_m"]].to_numpy(), axis=1)
    out = {"frames": int(pr[-1]) if pr and pr[-1].isdigit() else None, "size": f"{pr[0]}x{pr[1]}" if len(pr) > 2 else None,
           "calibration_median_m": round(float(np.median(err)), 3), "reference_points": int(len(t)),
           "reference_users": int(t["id"].nunique())}
    out["pass"] = out["frames"] == int(DURATION_S * 10) and out["calibration_median_m"] <= 0.6
    return out
