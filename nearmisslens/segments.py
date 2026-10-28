from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from meta_sam_parser import (CompletedOutcome, SegmentationMaskRecord, decode_mask_to_raster,
                             image_segmentation_format, video_segmentation_format)


@dataclass
class Detection:
    frame: int
    obj: str
    concept: str
    x1: float
    y1: float
    x2: float
    y2: float
    mask: np.ndarray
    score: float | None

    def centre(self) -> tuple[float, float, float]:
        """Centre (x, y) and angle (rad) of the mask's minimum-area rectangle, in source pixels."""
        ys, xs = np.nonzero(self.mask)
        if len(xs) < 3:
            return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2, 0.0
        pts = np.stack([xs + self.x1, ys + self.y1], axis=1).astype(np.float32)
        (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
        theta = np.deg2rad(ang if w >= h else ang + 90.0)
        return float(cx), float(cy), float(theta)

    def area(self) -> int:
        return int(self.mask.sum())


def parse_text(text: str, concept: str, video: bool, frame_offset: int = 0,
               dx: float = 0.0, dy: float = 0.0) -> list[Detection]:
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
