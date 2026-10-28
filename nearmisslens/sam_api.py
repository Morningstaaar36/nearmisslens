from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import cv2
import numpy as np

from .cache import file_sha256
from .cost import SAM_IMAGE_USD, sam_video_usd
from .meta_client import MetaClient, output_text
from .segments import Detection, parse_fast, parse_text

MODEL = "sam-3.1"
METADATA = {"mask_encoding": "one_bit", "include_confidence": "true"}


def png_data_url(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("PNG encode failed")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def segment_image(client: MetaClient, image: np.ndarray, concept: str, tag: str,
                  dx: float = 0.0, dy: float = 0.0) -> list[Detection]:
    url = png_data_url(image)
    request = {"model": MODEL, "metadata": METADATA, "concept": concept,
               "image_sha": hashlib.sha256(url.encode()).hexdigest()}
    payload = {"model": MODEL, "metadata": METADATA, "input": [{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": concept}, {"type": "input_image", "image_url": url}]}]}

    def cost(resp):
        n = (resp.get("usage") or {}).get("images_processed", 1) or 1
        return n * SAM_IMAGE_USD, MODEL, {"images": n}

    resp = client.cached("sam_image", request, lambda: client.stream_response(payload), cost,
                         SAM_IMAGE_USD, f"sam image {tag} '{concept}'")
    return parse_text(output_text(resp), concept, video=False, dx=dx, dy=dy)


def track_video(client: MetaClient, mp4: Path, concept: str, frames: int, tag: str,
                dx: float = 0.0, dy: float = 0.0, source_key: str | None = None) -> list[Detection]:
    """source_key identifies the clip independently of encoder bytes (source sha, window, crop)."""
    request = {"model": MODEL, "metadata": METADATA, "concept": concept,
               "source": source_key or file_sha256(mp4)}
    estimate = sam_video_usd(frames)

    def run():
        file_id = client.upload_file(mp4)
        payload = {"model": MODEL, "metadata": METADATA, "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": concept}, {"type": "input_video", "file_id": file_id}]}]}
        return client.stream_response(payload)

    def cost(resp):
        n = (resp.get("usage") or {}).get("video_frames_processed") or frames
        return sam_video_usd(int(n)), MODEL, {"frames": int(n)}

    resp = client.cached("sam_video", request, run, cost, estimate, f"sam video {tag} '{concept}'")
    return parse_fast(output_text(resp), concept, dx=dx, dy=dy)
