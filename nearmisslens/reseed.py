"""Re-seeding: SAM 3.1 finds most two-wheelers on single frames but loses many in video tracking (16 objects per
request). On keyframes of each segment, SAM 3.1 image detections that no video track covers are sent back to SAM 3.1
video as box prompts on the same tile clip, and the new tracks join the pipeline (BENCH_PREREG re-seeding trial)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import calibrate, fluid, pipeline, sam_api, tiling, tracks, video
from .meta_client import MetaClient
from .segments import Detection

KEYFRAMES = (0, 50)
MAX_OBJECTS = 16


def box_prompt(boxes: list[tuple[float, float, float, float]], frame: int, w: int, h: int) -> str:
    """SAM 3.1 object prompt: one object per box on one frame of the clip."""
    clamp = lambda v, hi: int(min(max(v, 0), hi - 1))  # x2 and y2 are inclusive, so at most w-1 and h-1
    objs = [f"{k + 1}<|box;x1={clamp(x1, w)};y1={clamp(y1, h)};x2={clamp(x2, w)};y2={clamp(y2, h)};w={w};h={h}|>"
            for k, (x1, y1, x2, y2) in enumerate(boxes[:MAX_OBJECTS])]
    return f"<{frame}f>" + ",".join(objs)


def _covered(video_dets: list[Detection], d: Detection, pad: float = 4.0) -> bool:
    cx, cy = (d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2
    return any(v.x1 - pad <= cx <= v.x2 + pad and v.y1 - pad <= cy <= v.y2 + pad for v in video_dets)


def _iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


def duplicates(new: list[Detection], old: list[Detection], iou: float = 0.5) -> set[str]:
    """Re-seeded track ids that overlap an existing track (IoU > iou) on at least half of their shared frames."""
    by_frame: dict[int, list[Detection]] = {}
    for d in old:
        by_frame.setdefault(d.frame, []).append(d)
    hits: dict[str, list[bool]] = {}
    for d in new:
        olds = by_frame.get(d.frame, [])
        if olds:
            hits.setdefault(d.obj, []).append(max(_iou(d, o) for o in olds) > iou)
    return {k for k, v in hits.items() if v and np.mean(v) >= 0.5}


def reseed_segment(client: MetaClient, src: Path, start_s: float, seg_len: float, tiles, raw: list[Detection],
                   concept: str, work: Path, tag: str, fps: float, stats: dict) -> list[Detection]:
    """Extra detections for one segment: per tile and keyframe, uncovered image detections tracked from box prompts."""
    src_sha = tiling.source_sha(src)
    frames = int(round(seg_len * fps))
    extra: list[Detection] = []
    for k, (x, y, w, h) in enumerate(tiles):
        mine = [d for d in raw if d.obj.startswith(f"t{k}:")]
        clip = video.cut(src, work / f"{src.stem}_{start_s:.2f}_{seg_len:.2f}_{x}-{y}-{w}x{h}.mp4", start_s, seg_len,
                         crop=(x, y, w, h))
        key = f"{src_sha}|start={start_s:.3f}|dur={seg_len:.3f}|crop={x},{y},{w},{h}"
        for f in KEYFRAMES:
            if f >= frames:
                continue
            img = video.frame_at(src, int(round(start_s * fps)) + f)[y:y + h, x:x + w]
            found = sam_api.segment_image(client, img, concept, f"reseed {tag} t{k} f{f}", dx=x, dy=y)
            stats["images"] = stats.get("images", 0) + 1
            missed = [d for d in found if not _covered([v for v in mine if v.frame == f], d)]
            if not missed:
                continue
            prompt = box_prompt([(d.x1 - x, d.y1 - y, d.x2 - x, d.y2 - y) for d in missed], f, w, h)
            new = sam_api.track_video(client, clip, prompt, frames, f"reseed {tag} t{k} f{f}", dx=x, dy=y,
                                      source_key=key)
            stats["requests"] = stats.get("requests", 0) + 1
            stats["seeds"] = stats.get("seeds", 0) + min(len(missed), MAX_OBJECTS)
            for d in new:
                d.obj = f"t{k}:r{f}:{d.obj}"
                d.concept = concept
            dup = duplicates(new, mine)
            kept = [d for d in new if d.obj not in dup]
            stats["kept_tracks"] = stats.get("kept_tracks", 0) + len({d.obj for d in kept})
            extra += kept
    return extra


def track_with_reseed(client: MetaClient, c: fluid.Clip, start_s: float, duration_s: float, concept, work: Path,
                      cal: calibrate.Calibration, reseed: bool = True, reseed_concepts=("scooter",)) -> tuple[pd.DataFrame, dict]:
    """The pipeline's segment tracking (cached SAM 3.1 video tracks) with optional re-seeding of reseed_concepts, as
    points. concept is one concept or a list (all tracked in each segment, as in pipeline.track_api)."""
    concepts = [concept] if isinstance(concept, str) else list(concept)
    info = video.probe(c.video)
    fps = info["fps"]
    tiles = tiling.grid(info["width"], info["height"])
    stats: dict = {}
    parts = []
    for k, t in enumerate(pipeline.segment_starts(start_s, duration_s)):
        seg_len = min(pipeline.SEGMENT_S + pipeline.OVERLAP_S, start_s + duration_s - t)
        raw = tiling.track_tiles(client, c.video, float(t), seg_len, concepts, work, tiles, f"{c.stem}@{t:.0f}")
        if reseed:
            for rc in (x for x in concepts if x in reseed_concepts):
                same = [d for d in raw if d.concept == rc]
                raw = raw + reseed_segment(client, c.video, float(t), seg_len, tiles, same, rc, work,
                                           f"{c.stem}@{t:.0f}", fps, stats)
        dets = tiling.merge_tiles(raw, tiles)
        pts = tracks.detections_to_points(dets, cal, fps, frame_offset=int(round(t * fps)) + 1, prefix=f"s{k}:")
        if not pts.empty:
            pts["segment"] = k
            parts.append(pts)
    points = pipeline.link_segments(pd.concat(parts, ignore_index=True), int(pipeline.OVERLAP_S * fps)) if parts else pd.DataFrame()
    return points, stats


def trial(client: MetaClient) -> dict:
    """Registered go/no-go on development frames 601-1200 with "scooter" (same window as PREREG change 8)."""
    from . import evaluate
    from .config import SETTINGS
    c = fluid.clip(*fluid.DEV)
    cal = pipeline.calibration_for(c)
    work = Path(SETTINGS.data_dir) / "work" / "experiment"
    frames = (601, 1200)
    out = {}
    for name, flag in (("baseline", False), ("reseeded", True)):
        pts, stats = track_with_reseed(client, c, 60.0, 60.0, "scooter", work, cal, reseed=flag)
        _, _, rows = evaluate.evaluate_tracks(pts, c, frames, f"reseed trial {name}", stitch=True)
        m = next((r for r in rows if r["class"] == "two_wheeler"), {})
        out[name] = {k: m.get(k) for k in ("recall", "precision", "idf1", "ref_points", "pred_points")} | {"stats": stats}
    b, r = out["baseline"], out["reseeded"]
    out["go"] = bool(r["recall"] - b["recall"] >= 0.10 and r["precision"] >= 0.8)
    return out
