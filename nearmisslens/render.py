"""Illustrate a proposed countermeasure on the real junction with Muse Image, then check the edit with SAM 3.1.

Muse Image edits are full re-renders, so only the hotspot disc is taken from the edit and real road users inside it
(SAM 3.1 masks on the original) are kept from the original frame. SAM 3.1 then looks for the countermeasure in the
disc before and after. Every output carries a visible AI-generated label."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import cv2
import numpy as np

from . import sam_api
from .calibrate import Calibration, metres_per_pixel
from .cost import IMAGE_USD
from .meta_client import MetaClient
from .config import MODELS

MODEL = MODELS["image"]
CROP_PX = 1024
ROAD_USERS = ("car", "scooter", "person")
LABEL = "AI-generated illustration (Muse Image) of a proposed countermeasure - not an engineering design"
KEEP = ("Keep the camera viewpoint, the road layout, buildings, trees, vehicles and people exactly as they are; "
        "change only what is described, in a realistic top-down aerial photo style.")


def crop_box(centre_px: np.ndarray, width: int, height: int, size: int = CROP_PX) -> tuple[int, int, int, int]:
    size = min(size, width, height)
    x0 = int(np.clip(round(centre_px[0] - size / 2), 0, width - size))
    y0 = int(np.clip(round(centre_px[1] - size / 2), 0, height - size))
    return x0, y0, size, size


def edit_image(client: MetaClient, image: np.ndarray, prompt: str, tag: str) -> np.ndarray:
    url = sam_api.png_data_url(image)
    body = {"model": MODEL, "prompt": prompt, "images": [{"image_url": url}], "n": 1, "output_format": "png",
            "size": f"{image.shape[1]}x{image.shape[0]}", "reasoning_strength": "high",
            "tool_enablement": {"enable_image_search": False, "enable_web_search": False, "enable_shell": False}}
    request = {k: v for k, v in body.items() if k != "images"} | {"image_sha": hashlib.sha256(url.encode()).hexdigest()}
    resp = client.cached("image_edit", request, lambda: client.post_json("/images/edits", body),
                         lambda r: (IMAGE_USD * len(r.get("data") or []), MODEL, {"images": len(r.get("data") or [])}),
                         IMAGE_USD, f"muse image {tag}",
                         complete=lambda r: bool(r.get("data")) and bool(r["data"][0].get("b64_json")))
    raw = np.frombuffer(base64.b64decode(resp["data"][0]["b64_json"]), np.uint8)
    out = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if out is None:
        raise ValueError(f"muse image {tag}: undecodable image")
    return cv2.resize(out, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_AREA)


def _union_mask(dets, shape) -> np.ndarray:
    m = np.zeros(shape[:2], bool)
    for d in dets:
        if d.mask is not None and d.mask.shape == m.shape:
            m |= d.mask > 0
        else:
            m[int(max(d.y1, 0)):int(d.y2), int(max(d.x1, 0)):int(d.x2)] = True
    return m


def disc_alpha(shape, centre: tuple[float, float], radius: float, feather: float) -> np.ndarray:
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    d = np.hypot(xx - centre[0], yy - centre[1])
    return np.clip((radius - d) / max(feather, 1.0) + 0.5, 0.0, 1.0)


def composite(before: np.ndarray, after: np.ndarray, alpha: np.ndarray, keep: np.ndarray) -> np.ndarray:
    a = alpha.copy()
    a[cv2.dilate(keep.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0] = 0.0
    a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 3)[..., None]
    return (a * after + (1 - a) * before).astype(np.uint8)


def label(image: np.ndarray, text: str = LABEL) -> np.ndarray:
    out = image.copy()
    scale = out.shape[1] / 1600
    h = int(44 * scale) + 8
    out[-h:] = (out[-h:] * 0.35).astype(np.uint8)
    cv2.putText(out, text, (10, out.shape[0] - h // 3), cv2.FONT_HERSHEY_SIMPLEX, 0.9 * scale, (255, 255, 255),
                max(1, int(2 * scale)), cv2.LINE_AA)
    return out


def concept_area(client: MetaClient, image: np.ndarray, concept: str, region: np.ndarray, tag: str) -> float:
    """Share of the region covered by SAM 3.1 detections of the concept."""
    dets = sam_api.segment_image(client, image, concept, tag)
    m = _union_mask(dets, image.shape)
    return float((m & region).sum() / max(region.sum(), 1))


def render_fix(client: MetaClient, frame: np.ndarray, cal: Calibration, hotspot_m: tuple[float, float],
               radius_m: float, countermeasure: str, spec: dict, out_dir: Path, tag: str) -> dict:
    """Before/after illustration of one countermeasure at one hotspot, with a SAM 3.1 check of the edit."""
    centre = cal.to_pixels(np.array([hotspot_m]))[0]
    x0, y0, w, h = crop_box(centre, frame.shape[1], frame.shape[0])
    before = frame[y0:y0 + h, x0:x0 + w].copy()
    c = (centre[0] - x0, centre[1] - y0)
    r_px = radius_m / metres_per_pixel(cal, centre)
    region = disc_alpha(before.shape, c, r_px, 1.0) > 0.5
    users = []
    for concept in ROAD_USERS:
        users += sam_api.segment_image(client, before, concept, f"{tag} users")
    keep = _union_mask(users, before.shape)
    edited = edit_image(client, before, f"{spec['prompt']} {KEEP}", tag)
    after = composite(before, edited, disc_alpha(before.shape, c, r_px, r_px * 0.15), keep)
    area_before = concept_area(client, before, spec["check"], region, f"{tag} check before")
    area_after = concept_area(client, after, spec["check"], region, f"{tag} check after")
    out_dir.mkdir(parents=True, exist_ok=True)
    pair = np.concatenate([label(before, "Observed (drone video frame)"), label(after)], axis=1)
    cv2.circle(pair, (int(c[0]), int(c[1])), int(r_px), (0, 200, 255), 2)
    cv2.circle(pair, (int(c[0]) + w, int(c[1])), int(r_px), (0, 200, 255), 2)
    path = out_dir / f"{tag}.png"
    cv2.imwrite(str(path), pair)
    return {"countermeasure": countermeasure, "image": str(path), "crop": [x0, y0, w, h],
            "radius_px": round(float(r_px), 1), "protected_road_users": len(users),
            "check_concept": spec["check"], "area_before": round(area_before, 4), "area_after": round(area_after, 4),
            "check_passed": area_after > area_before}
