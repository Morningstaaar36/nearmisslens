from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TAG_PIXEL_SCALE = 33550
TAG_TIEPOINT = 33922
TAG_TRANSFORM = 34264
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}


def geotiff_transform(path: Path) -> tuple[float, float, float, float]:
    """(x0, y0, sx, sy) such that world = (x0 + col*sx, y0 - row*sy), from GeoTIFF tie point and pixel scale."""
    with open(path, "rb") as f:
        head = f.read(16)
        bo = "<" if head[:2] == b"II" else ">"
        big = struct.unpack(bo + "H", head[2:4])[0] == 43
        f.seek(8 if big else 4)
        off = struct.unpack(bo + ("Q" if big else "I"), f.read(8 if big else 4))[0]
        f.seek(off)
        n = struct.unpack(bo + ("Q" if big else "H"), f.read(8 if big else 2))[0]
        tags = {}
        for _ in range(n):
            ent = f.read(20 if big else 12)
            tag, typ = struct.unpack(bo + "HH", ent[:4])
            cnt = struct.unpack(bo + ("Q" if big else "I"), ent[4:12] if big else ent[4:8])[0]
            raw = ent[12:20] if big else ent[8:12]
            if tag in (TAG_PIXEL_SCALE, TAG_TIEPOINT, TAG_TRANSFORM):
                size = TYPE_SIZE[typ] * cnt
                if size > len(raw):
                    pos = f.tell()
                    f.seek(struct.unpack(bo + ("Q" if big else "I"), raw)[0])
                    raw = f.read(size)
                    f.seek(pos)
                tags[tag] = struct.unpack(bo + TYPE_FMT[typ] * cnt, raw[:size])
    if TAG_TRANSFORM in tags:
        m = tags[TAG_TRANSFORM]
        return float(m[3]), float(m[7]), float(m[0]), float(-m[5])
    sx, sy = tags[TAG_PIXEL_SCALE][:2]
    _, _, _, x0, y0, _ = tags[TAG_TIEPOINT][:6]
    return float(x0), float(y0), float(sx), float(sy)


@dataclass
class Calibration:
    H: np.ndarray
    transform: tuple[float, float, float, float]
    inliers: int

    def to_metres(self, xy: np.ndarray) -> np.ndarray:
        pts = cv2.perspectiveTransform(np.asarray(xy, np.float64).reshape(-1, 1, 2), self.H).reshape(-1, 2)
        x0, y0, sx, sy = self.transform
        return np.stack([x0 + pts[:, 0] * sx, y0 - pts[:, 1] * sy], axis=1)

    def to_pixels(self, xy_m: np.ndarray) -> np.ndarray:
        x0, y0, sx, sy = self.transform
        m = np.asarray(xy_m, np.float64).reshape(-1, 2)
        base = np.stack([(m[:, 0] - x0) / sx, (y0 - m[:, 1]) / sy], axis=1)
        return cv2.perspectiveTransform(base.reshape(-1, 1, 2), np.linalg.inv(self.H)).reshape(-1, 2)


def metres_per_pixel(cal: Calibration, centre_px: np.ndarray, step: float = 50.0) -> float:
    pts = np.array([centre_px, centre_px + [step, 0.0], centre_px + [0.0, step]], float)
    m = cal.to_metres(pts)
    return float((np.linalg.norm(m[1] - m[0]) + np.linalg.norm(m[2] - m[0])) / (2 * step))


def calibrate(frame: np.ndarray, base_map: Path, max_features: int = 20000, work_width: int = 1920) -> Calibration:
    base = cv2.imread(str(base_map), cv2.IMREAD_COLOR)
    f1 = work_width / frame.shape[1]
    f2 = work_width / base.shape[1]
    g1 = cv2.cvtColor(cv2.resize(frame, None, fx=f1, fy=f1, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(cv2.resize(base, None, fx=f2, fy=f2, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    det = cv2.SIFT_create(nfeatures=max_features)
    k1, d1 = det.detectAndCompute(g1, None)
    k2, d2 = det.detectAndCompute(g2, None)
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.75 * n.distance]
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2) / f1
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2) / f2
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    return Calibration(H, geotiff_transform(base_map), int(inl.sum()))


def reprojection_error(cal: Calibration, px: np.ndarray, metres: np.ndarray) -> dict:
    err = np.linalg.norm(cal.to_metres(px) - metres, axis=1)
    return {"median_m": float(np.median(err)), "p90_m": float(np.percentile(err, 90)), "n": int(len(err))}
