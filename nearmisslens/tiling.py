from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import sam_api, video
from .assign import nearest_pairs, one_to_one
from .cache import source_sha
from .cost import SAM_MIN_FRAMES, sam_video_usd
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


SAM_MAX_OBJECTS = 16
OVERLAP_FRAMES = 5


def _box_centres(ds: list[Detection]) -> np.ndarray:
    return np.array([[(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2] for d in ds])


def link_pieces(first: list[Detection], second: list[Detection], overlap: range, radius_px: float = 30.0) -> list[Detection]:
    """Relabel `second` with ids from `first` where boxes coincide in the overlapping frames; drop duplicates there."""
    votes: dict[tuple[str, str], int] = {}
    for f in overlap:
        a = [d for d in first if d.frame == f]
        b = [d for d in second if d.frame == f]
        for p, q in nearest_pairs(_box_centres(a), _box_centres(b), radius_px):
            votes[(a[p].obj, b[q].obj)] = votes.get((a[p].obj, b[q].obj), 0) + 1
    rename = one_to_one(votes, max(1, len(overlap) // 2))
    in_overlap = set(overlap)
    out = list(first)
    for d in second:
        if d.frame in in_overlap and d.obj in rename:
            continue
        d.obj = rename.get(d.obj, d.obj)
        out.append(d)
    return out


_STATS_LOCK = threading.Lock()


def _count(stats: dict, key: str) -> None:
    with _STATS_LOCK:
        stats[key] = stats.get(key, 0) + 1


def track_job(client: MetaClient, src: Path, src_sha: str, fps: float, start_s: float, duration_s: float,
              tile: tuple[int, int, int, int], concept: str, work: Path, tag: str, stats: dict,
              path: str = "") -> list[Detection]:
    """One SAM 3.1 video request for a tile and window; if it returns SAM_MAX_OBJECTS distinct objects (the API's
    per-request cap) it is split in time, down to the 50-frame billing minimum, and the halves are re-linked.
    Detection frames are relative to start_s."""
    x, y, w, h = tile
    frames = int(round(duration_s * fps))
    clip = video.cut(src, work / f"{src.stem}_{start_s:.2f}_{duration_s:.2f}_{x}-{y}-{w}x{h}.mp4", start_s,
                     duration_s, crop=(x, y, w, h))
    key = f"{src_sha}|start={start_s:.3f}|dur={duration_s:.3f}|crop={x},{y},{w},{h}"
    dets = sam_api.track_video(client, clip, concept, frames, f"{tag}{path}", dx=x, dy=y, source_key=key)
    _count(stats, "requests")
    for d in dets:
        d.obj = f"{path}{d.obj}"
    saturated = len({d.obj for d in dets}) >= SAM_MAX_OBJECTS
    half = frames // 2
    if not saturated:
        return dets
    if half < SAM_MIN_FRAMES:
        _count(stats, "saturated_leaves")
        return dets
    _count(stats, "splits")
    first = track_job(client, src, src_sha, fps, start_s, (half + OVERLAP_FRAMES) / fps, tile, concept, work, tag,
                      stats, path + "a")
    second = track_job(client, src, src_sha, fps, start_s + half / fps, (frames - half) / fps, tile, concept, work,
                       tag, stats, path + "b")
    for d in second:
        d.frame += half
    return link_pieces(first, second, range(half, half + OVERLAP_FRAMES))


def track_tiles(client: MetaClient, src: Path, start_s: float, duration_s: float, concepts: list[str],
                work: Path, tiles: list[tuple[int, int, int, int]] | None = None, tag: str = "",
                workers: int = 8, stats: dict | None = None) -> list[Detection]:
    info = video.probe(src)
    tiles = tiles or grid(info["width"], info["height"])
    frames = int(round(duration_s * info["fps"]))
    client.check_budget(estimate_usd(frames, len(tiles), len(concepts)), f"tiles {tag}")
    src_sha = source_sha(src)
    stats = stats if stats is not None else {}

    def run(job):
        k, concept = job
        dets = track_job(client, src, src_sha, info["fps"], start_s, duration_s, tiles[k], concept, work,
                         f"{tag}t{k}", stats)
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
    """Join tile-local tracks that are the same object in overlap zones (one-to-one per tile pair, at most one track
    per tile in a group); keep the detection farthest from its tile edge per object per frame."""
    by_frame: dict[tuple[int, str], list[Detection]] = {}
    for d in dets:
        by_frame.setdefault((d.frame, d.concept), []).append(d)
    votes: dict[tuple[str, str, str], dict[tuple[str, str], int]] = {}
    for (_, concept), ds in by_frame.items():
        by_tile: dict[str, list[Detection]] = {}
        for d in ds:
            by_tile.setdefault(d.obj.split(":")[0], []).append(d)
        names = sorted(by_tile)
        for i, ta in enumerate(names):
            for tb in names[i + 1:]:
                a, b = by_tile[ta], by_tile[tb]
                ca = np.array([d.centre()[:2] for d in a])
                cb = np.array([d.centre()[:2] for d in b])
                v = votes.setdefault((concept, ta, tb), {})
                for p, q in nearest_pairs(ca, cb, radius_px):
                    v[(a[p].obj, b[q].obj)] = v.get((a[p].obj, b[q].obj), 0) + 1
    parent: dict[str, str] = {}
    members: dict[str, set[str]] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for (concept, _, _), v in sorted(votes.items()):
        for right, left in sorted(one_to_one(v, min_shared).items()):
            ra, rb = find(f"{concept}|{left}"), find(f"{concept}|{right}")
            if ra == rb:
                continue
            ta = members.get(ra, {left.split(":")[0]})
            tb = members.get(rb, {right.split(":")[0]})
            if ta & tb:
                continue
            parent[ra] = rb
            members[rb] = ta | tb
    merged: dict[tuple[int, str], Detection] = {}
    best: dict[tuple[int, str], float] = {}
    for d in dets:
        gid = find(f"{d.concept}|{d.obj}")
        key = (d.frame, gid)
        k = int(d.obj.split(":")[0][1:])
        score = _edge_distance(d, tiles, k)
        if key not in merged or score > best[key]:
            merged[key] = replace(d, obj=gid.split("|", 1)[1])
            best[key] = score
    return list(merged.values())
