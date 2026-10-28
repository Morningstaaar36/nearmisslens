from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np
from meta_sam_parser import (CompletedOutcome, SegmentationMask, SegmentationMaskRecord, decode_mask_to_raster,
                             image_segmentation_format, video_segmentation_format)

ENCODING = {"!": "one_bit", "~": "lossless"}
FRAME_RE = re.compile(r"<(\d+)f>")
OBJECT_RE = re.compile(r"(\d+)<\|box;([^|]*)\|>(?:<\|mask;([^|]*)\|>)?")


@dataclass
class Detection:
    frame: int
    obj: str
    concept: str
    x1: float
    y1: float
    x2: float
    y2: float
    mask: np.ndarray | None
    score: float | None
    payload: tuple[str, str, int, int] | None = None

    def centre(self) -> tuple[float, float, float]:
        """Centre (x, y) and angle (rad) of the mask's minimum-area rectangle in source pixels.

        Without a decoded mask, the box centre is used (equal to the rectangle centre for a centrally
        symmetric shape) and the angle is unknown (nan).
        """
        if self.mask is None:
            return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2, float("nan")
        ys, xs = np.nonzero(self.mask)
        if len(xs) < 3:
            return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2, float("nan")
        pts = np.stack([xs + self.x1, ys + self.y1], axis=1).astype(np.float32)
        (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
        theta = np.deg2rad(ang if w >= h else ang + 90.0)
        return float(cx), float(cy), float(theta)


def _fields(body: str) -> dict[str, str]:
    out = {}
    for part in body.split(";"):
        k, _, v = part.partition("=")
        out[k] = v
    return out


def parse_fast(text: str, concept: str, frame_offset: int = 0, dx: float = 0.0, dy: float = 0.0) -> list[Detection]:
    """Boxes and undecoded mask payloads from SAM video output, following the documented wire format.

    Box bounds are returned half-open like the official parser (x2, y2 on the wire are inclusive).
    """
    out: list[Detection] = []
    for line in text.split("\n"):
        m = FRAME_RE.match(line)
        if not m:
            continue
        frame = int(m.group(1)) + frame_offset
        for obj, box, mask in OBJECT_RE.findall(line[m.end():]):
            b = _fields(box)
            score = float(b["c"]) if b.get("c") else None
            payload = None
            if mask:
                mf = _fields(mask)
                h, w, rest = mf["data"].split(",", 2)
                payload = (ENCODING[rest[0]], rest, int(w), int(h))
            out.append(Detection(frame, obj, concept, float(b["x1"]) + dx, float(b["y1"]) + dy,
                                 float(b["x2"]) + 1 + dx, float(b["y2"]) + 1 + dy, None, score, payload))
    return out


def _decode(payload: tuple[str, str, int, int]) -> np.ndarray:
    enc, data, w, h = payload
    raster = decode_mask_to_raster(SegmentationMask(enc, data, w, h))
    return np.frombuffer(raster, dtype=np.uint8).reshape(h, w).copy()


def decode_masks(dets: list[Detection], workers: int | None = None) -> None:
    """Decode the mask payloads of the given detections in place, in parallel processes."""
    todo = [d for d in dets if d.mask is None and d.payload is not None]
    if not todo:
        return
    n = workers or max(1, (os.cpu_count() or 2) - 1)
    if n == 1 or len(todo) < 32:
        masks = [_decode(d.payload) for d in todo]
    else:
        with ProcessPoolExecutor(n) as ex:
            masks = list(ex.map(_decode, [d.payload for d in todo], chunksize=16))
    for d, m in zip(todo, masks):
        d.mask = m


def parse_text(text: str, concept: str, video: bool, frame_offset: int = 0,
               dx: float = 0.0, dy: float = 0.0) -> list[Detection]:
    """Official meta_sam_parser path: validates and decodes every mask (slow for long videos)."""
    fmt = video_segmentation_format() if video else image_segmentation_format()
    parser = fmt.create_parser()
    parser.push(text, emit=False)
    result = parser.finish(CompletedOutcome()).result
    out: list[Detection] = []
    for rec in result.records:
        if not isinstance(rec, SegmentationMaskRecord):
            continue
        raster = decode_mask_to_raster(rec.mask)
        mask = np.frombuffer(raster, dtype=np.uint8).reshape(rec.mask.height, rec.mask.width).copy()
        b = rec.bounds
        frame = (rec.frame.frame_index if rec.frame is not None else 0) + frame_offset
        out.append(Detection(frame, rec.object_id, concept, b.left + dx, b.top + dy, b.right + dx,
                             b.bottom + dy, mask, rec.confidence))
    return out
