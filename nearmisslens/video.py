from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,r_frame_rate,nb_frames", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"codec": s["codec_name"], "width": int(s["width"]), "height": int(s["height"]),
            "fps": float(num) / float(den), "frames": int(s.get("nb_frames", 0) or 0)}


def cut(src: Path, out: Path, start_s: float, duration_s: float, crop: tuple[int, int, int, int] | None = None,
        width: int | None = None, crf: int = 20) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    vf = []
    if crop:
        x, y, w, h = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    if width:
        vf.append(f"scale={width}:-2")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start_s:.3f}", "-i", str(src), "-t", f"{duration_s:.3f}",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-movflags", "+faststart"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    tmp = out.with_name(f".{out.stem}.part{out.suffix}")
    try:
        subprocess.run(cmd + [str(tmp)], check=True)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def frames(path: Path, start: int = 0, count: int | None = None, step: int = 1):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    i = start
    try:
        while count is None or i < start + count:
            ok, img = cap.read()
            if not ok:
                break
            if (i - start) % step == 0:
                yield i, img
            i += 1
    finally:
        cap.release()


def frame_at(path: Path, index: int) -> np.ndarray:
    for _, img in frames(path, index, 1):
        return img
    raise IndexError(index)
