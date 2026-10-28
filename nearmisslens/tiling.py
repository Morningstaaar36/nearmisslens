from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import sam_api, video
from .cache import source_sha
from .cost import sam_video_usd
from .meta_client import MetaClient
from .segments import Detection


def grid(width: int, height: int, cols: int = 2, rows: int = 2, overlap: int = 128) -> list[tuple[int, int, int, int]]:
    tw, th = width // cols, height // rows
    tiles = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, c * tw - overlap // 2)
            y0 = max(0, r * th - overlap // 2)
            x1 = min(width, (c + 1) * tw + overlap // 2)
            y1 = min(height, (r + 1) * th + overlap // 2)
            tiles.append((x0, y0, (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2))
    return tiles


def estimate_usd(frames: int, n_tiles: int, n_concepts: int) -> float:
    return n_tiles * n_concepts * sam_video_usd(frames)


def track_tiles(client: MetaClient, src: Path, start_s: float, duration_s: float, concepts: list[str],
                work: Path, tiles: list[tuple[int, int, int, int]] | None = None, tag: str = "",
                workers: int = 8) -> list[Detection]:
    info = video.probe(src)
    tiles = tiles or grid(info["width"], info["height"])
    frames = int(round(duration_s * info["fps"]))
    client.meter.check(estimate_usd(frames, len(tiles), len(concepts)), f"tiles {tag}")

    def cut(k):
        x, y, w, h = tiles[k]
        return video.cut(src, work / f"{src.stem}_{start_s:.1f}_{duration_s:.1f}_t{k}.mp4", start_s, duration_s,
                         crop=(x, y, w, h))

    with ThreadPoolExecutor(min(4, len(tiles))) as ex:
        clips = list(ex.map(cut, range(len(tiles))))

    src_sha = source_sha(src)

    def run(job):
        k, concept = job
        x, y, w, h = tiles[k]
        key = f"{src_sha}|start={start_s:.3f}|dur={duration_s:.3f}|crop={x},{y},{w},{h}"
        dets = sam_api.track_video(client, clips[k], concept, frames, f"{tag}t{k}", dx=x, dy=y, source_key=key)
        for d in dets:
            d.obj = f"t{k}:{d.obj}"
        return dets

    jobs = [(k, c) for k in range(len(tiles)) for c in concepts]
    out: list[Detection] = []
    with ThreadPoolExecutor(workers) as ex:
        for dets in ex.map(run, jobs):
            out.extend(dets)
    return out


def _edge_distance(d: Detection, tiles, k: int) -> float:
    x, y, w, h = tiles[k]
    cx, cy, _ = d.centre()
    return min(cx - x, x + w - cx, cy - y, y + h - cy)


def merge_tiles(dets: list[Detection], tiles, radius_px: float = 25.0, min_shared: int = 3) -> list[Detection]:
    """Union tile-local tracks that are the same object in overlap zones; keep one detection per object per frame."""
    by_frame: dict[tuple[int, str], list[Detection]] = {}
    for d in dets:
        by_frame.setdefault((d.frame, d.concept), []).append(d)
    parent: dict[str, str] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    shared: dict[tuple[str, str], int] = {}
    for (_, _), ds in by_frame.items():
        if len(ds) < 2:
            continue
        c = np.array([d.centre()[:2] for d in ds])
        tile_of = [d.obj.split(":")[0] for d in ds]
        D = np.linalg.norm(c[:, None] - c[None], axis=2)
        for i, j in zip(*np.nonzero(np.triu(D < radius_px, 1))):
            if tile_of[i] != tile_of[j]:
                key = tuple(sorted((f"{ds[i].concept}|{ds[i].obj}", f"{ds[j].concept}|{ds[j].obj}")))
                shared[key] = shared.get(key, 0) + 1
    for (a, b), n in shared.items():
        if n >= min_shared:
            parent[find(a)] = find(b)
    merged: dict[tuple[int, str], Detection] = {}
    best: dict[tuple[int, str], float] = {}
    for d in dets:
        gid = find(f"{d.concept}|{d.obj}")
        key = (d.frame, gid)
        k = int(d.obj.split(":")[0][1:])
        score = _edge_distance(d, tiles, k)
        if key not in merged or score > best[key]:
            merged[key] = Detection(d.frame, gid.split("|", 1)[1], d.concept, d.x1, d.y1, d.x2, d.y2, d.mask, d.score)
            best[key] = score
    return list(merged.values())
