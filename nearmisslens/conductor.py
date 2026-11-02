"""Budgeted perception: decide which (tile, window, concept) SAM 3.1 tracking jobs to run.

Three policies spend the same nominal budget and are scored by how many reference conflicts their tracks recover:
uniform (every tile in time order), greedy (most motion first) and the Muse Wonder agent, which uses the tools below.
Tracking results are cached per job, so policies that choose the same job share the actual API cost.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from . import conflicts, fluid, sam_api, tiling, tracks, video
from .agent import Tool, run_agent
from .calibrate import Calibration
from .cost import sam_video_usd, token_usd
from .meta_client import MetaClient, output_text
from .segments import Detection
from .config import MODELS

AGENT_MODEL = MODELS["large"]
LOOK_MODEL = MODELS["reader"]
DEFAULT_CONCEPTS = ("car", "scooter")


@dataclass
class Site:
    clip: fluid.Clip
    cal: Calibration
    fps: float
    width: int
    height: int
    tiles: list[tuple[int, int, int, int]]
    window_s: float
    duration_s: float
    work: Path

    @property
    def windows(self) -> list[float]:
        return list(np.arange(0.0, self.duration_s - 1e-6, self.window_s))

    def window_len(self, w: int) -> float:
        return min(self.window_s, self.duration_s - self.windows[w])

    def job_usd(self, w: int) -> float:
        return sam_video_usd(int(round(self.window_len(w) * self.fps)))


@dataclass
class Ledger:
    budget_usd: float
    spent_usd: float = 0.0
    jobs: list[tuple[int, int, str]] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)

    def remaining(self) -> float:
        return self.budget_usd - self.spent_usd


def make_site(c: fluid.Clip, cal: Calibration, work: Path, window_s: float = 30.0, grid: tuple[int, int] = (2, 2)) -> Site:
    info = video.probe(c.video)
    duration = info["frames"] / info["fps"]
    return Site(c, cal, info["fps"], info["width"], info["height"],
                tiling.grid(info["width"], info["height"], cols=grid[0], rows=grid[1]), window_s, duration, work)


def run_job(client: MetaClient, site: Site, led: Ledger, tile: int, w: int, concept: str) -> dict:
    if not (0 <= tile < len(site.tiles) and 0 <= w < len(site.windows)):
        return {"status": "rejected", "reason": f"tile must be in 0..{len(site.tiles) - 1}, window in 0..{len(site.windows) - 1}"}
    if (tile, w, concept) in led.jobs:
        return {"status": "already tracked"}
    cost = site.job_usd(w)
    if cost > led.remaining() + 1e-9:
        return {"status": "rejected", "reason": f"needs ${cost:.3f}, remaining ${led.remaining():.3f}"}
    start, length = site.windows[w], site.window_len(w)
    raw = tiling.track_tiles(client, site.clip.video, start, length, [concept], site.work, [site.tiles[tile]],
                             tag=f"{site.clip.stem}@w{w}", workers=1)
    for d in raw:
        d.obj = f"w{w}:t{tile}:{d.obj}"
        d.frame += int(round(start * site.fps))
    led.detections.extend(raw)
    led.spent_usd += cost
    led.jobs.append((tile, w, concept))
    return {"status": "tracked", "tracks": len({d.obj for d in raw}), "cost_usd": round(cost, 4),
            "remaining_usd": round(led.remaining(), 4)}


def states_from(site: Site, dets: list[Detection]) -> pd.DataFrame:
    if not dets:
        return pd.DataFrame(columns=conflicts.STATE_COLUMNS)
    pts = tracks.detections_to_points(dets, site.cal, site.fps, frame_offset=1)
    return tracks.smooth_states(pts, site.fps)


def motion_energy(site: Site, w: int, samples: int = 6, scale: float = 0.25) -> list[float]:
    """Mean absolute frame difference per tile across a window (no model involved)."""
    start = int(round(site.windows[w] * site.fps))
    n = int(round(site.window_len(w) * site.fps))
    idx = np.linspace(start, start + n - 2, samples).astype(int)
    energy = np.zeros(len(site.tiles))
    for f in idx:
        pair = [cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) for _, img in video.frames(site.clip.video, int(f), 2)]
        if len(pair) < 2:
            continue
        d = cv2.resize(cv2.absdiff(pair[0], pair[1]), None, fx=scale, fy=scale).astype(float)
        for k, (x, y, tw, th) in enumerate(site.tiles):
            energy[k] += d[int(y * scale):int((y + th) * scale), int(x * scale):int((x + tw) * scale)].mean()
    return list(energy / samples)


def pedestrian_phase(site: Site, w: int) -> dict:
    sig = fluid.load_signals(site.clip)
    t0, t1 = site.windows[w], site.windows[w] + site.window_len(w)
    ped = sig[(sig["turn"] == "p") & (sig["state"] == "G") & (sig["end_time"] > t0) & (sig["begin_time"] < t1)]
    out = {}
    for d, g in ped.groupby("direction"):
        overlap = (np.minimum(g["end_time"], t1) - np.maximum(g["begin_time"], t0)).clip(lower=0).sum()
        out[d] = round(float(overlap / (t1 - t0)), 2)
    return {"walk_fraction_by_approach": out, "right_turns_signalised": fluid.has_right_turn_control(sig)}


LOOK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["road_users"],
               "properties": {"road_users": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["noun_phrase", "approx_count"],
                   "properties": {"noun_phrase": {"type": "string"}, "approx_count": {"type": "integer"}}}}}}


def look(client: MetaClient, site: Site, tile: int, w: int) -> dict:
    """Muse Spark names the kinds of road users visible in one tile at the window's middle frame."""
    f = int(round((site.windows[w] + site.window_len(w) / 2) * site.fps))
    x, y, tw, th = site.tiles[tile]
    crop = video.frame_at(site.clip.video, f)[y:y + th, x:x + tw]
    url = sam_api.png_data_url(cv2.resize(crop, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
    request = {"model": LOOK_MODEL, "frame": f, "tile": [x, y, tw, th], "schema": LOOK_SCHEMA}
    payload = {"model": LOOK_MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 4000,
               "instructions": "List the kinds of road users visible in this top-down traffic image as short noun phrases "
                               "suitable as segmentation prompts (for example 'car', 'scooter', 'cargo tricycle', 'pedestrian'), "
                               "with an approximate count each. Only list what is visible.",
               "text": {"format": {"type": "json_schema", "name": "road_users", "schema": LOOK_SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": url}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(LOOK_MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), LOOK_MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("spark_look", request, lambda: client.create_response(payload), cost, 0.01,
                         f"look t{tile} w{w}", require_text=True)
    return json.loads(output_text(resp))


def policy_uniform(client: MetaClient, site: Site, budget: float, concepts=DEFAULT_CONCEPTS) -> Ledger:
    led = Ledger(budget)
    for w in range(len(site.windows)):
        for t in range(len(site.tiles)):
            for c in concepts:
                if run_job(client, site, led, t, w, c)["status"] == "rejected":
                    return led
    return led


def policy_greedy(client: MetaClient, site: Site, budget: float, concepts=DEFAULT_CONCEPTS) -> Ledger:
    led = Ledger(budget)
    ranked = sorted(((e, t, w) for w in range(len(site.windows)) for t, e in enumerate(motion_energy(site, w))),
                    reverse=True)
    for _, t, w in ranked:
        for c in concepts:
            if run_job(client, site, led, t, w, c)["status"] == "rejected":
                return led
    return led


AGENT_INSTRUCTIONS = (
    "You direct a road-safety near-miss audit of a signalised intersection filmed from a drone. Tracking road users "
    "with SAM 3.1 costs money per tile, time window and concept, and the budget cannot cover everything. Your goal is "
    "to recover as many real near-misses between road users as possible, especially involving pedestrians and "
    "two-wheelers. Use the free tools (site summary, motion energy, pedestrian phases) and the cheap look tool to "
    "decide where and when to track, and which concepts to track (SAM accepts any short noun phrase). Track the "
    "interacting road users in the same tile and window, since a near-miss needs both. Stop with finish when the "
    "budget is spent or more tracking would not help. Explain each choice briefly in the reason fields."
)


def agent_tools(client: MetaClient, site: Site, led: Ledger) -> list[Tool]:
    obj = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
    tile_w = {"tile": {"type": "integer"}, "window": {"type": "integer"}}
    return [
        Tool("site_summary", "Tiles, windows, cost per tracking job and remaining budget.", obj({}, []),
             lambda: {"tiles": [{"id": k, "rect_px": list(r)} for k, r in enumerate(site.tiles)],
                      "windows": [{"id": w, "start_s": s, "length_s": site.window_len(w)} for w, s in enumerate(site.windows)],
                      "cost_per_job_usd": round(site.job_usd(0), 4), "remaining_usd": round(led.remaining(), 4),
                      "default_concepts": list(DEFAULT_CONCEPTS)}),
        Tool("motion_energy", "Free: activity per tile in a window (mean frame difference).",
             obj({"window": {"type": "integer"}}, ["window"]),
             lambda window: {"window": window, "energy_by_tile": [round(e, 2) for e in motion_energy(site, window)]}),
        Tool("pedestrian_phase", "Free: share of the window with a pedestrian WALK signal per approach.",
             obj({"window": {"type": "integer"}}, ["window"]), lambda window: pedestrian_phase(site, window)),
        Tool("look", "Cheap: Muse Spark lists road-user kinds visible in a tile at the window's middle frame.",
             obj(tile_w, ["tile", "window"]), lambda tile, window: look(client, site, tile, window)),
        Tool("track", "Paid: run SAM 3.1 tracking for one concept in one tile and window.",
             obj({**tile_w, "concept": {"type": "string"}, "reason": {"type": "string"}},
                 ["tile", "window", "concept", "reason"]),
             lambda tile, window, concept, reason: run_job(client, site, led, tile, window, concept)),
        Tool("finish", "Stop the audit planning.", obj({"reason": {"type": "string"}}, ["reason"]),
             lambda reason: {"ok": True, "spent_usd": round(led.spent_usd, 4)}),
    ]


def policy_agent(client: MetaClient, site: Site, budget: float, agent_budget_usd: float = 3.0,
                 max_turns: int = 40, model: str = AGENT_MODEL) -> tuple[Ledger, dict]:
    led = Ledger(budget)
    task = (f"Plan the tracking for clip {site.clip.site}/{site.clip.stem}. The tracking budget is ${budget:.2f}. "
            "Start with site_summary.")
    run = run_agent(client, model, AGENT_INSTRUCTIONS, task, agent_tools(client, site, led), max_turns,
                    agent_budget_usd, effort="medium", tag=f"conductor {site.clip.stem}")
    return led, {"decision_log": run.decision_log(), "agent_usd": run.usd, "turns": run.turns, "stopped": run.stopped,
                 "final_text": run.final_text}


def conflict_recall(site: Site, led: Ledger, ref_events: pd.DataFrame, ref_states: pd.DataFrame) -> dict:
    """Share of reference TTC events whose two users are both tracked, at the event frame, by this policy."""
    from .match import id_map
    st = states_from(site, led.detections)
    out = {"reference": int(len(ref_events)), "spent_usd": round(led.spent_usd, 4), "jobs": len(led.jobs)}
    if st.empty or ref_events.empty:
        return {**out, "recovered": 0, "recall": 0.0, "vru_reference": 0, "vru_recall": 0.0}
    pmap = id_map(st, ref_states)
    covered = {(pmap[pid], fr) for pid, fr in zip(st["id"], st["frame"]) if pid in pmap}
    hit = np.array([(e.id_1, int(e.frame_min_ttc)) in covered and (e.id_2, int(e.frame_min_ttc)) in covered
                    for e in ref_events.itertuples()])
    vru = ((ref_events["cls_1"] != "vehicle") | (ref_events["cls_2"] != "vehicle")).to_numpy()
    return {**out, "recovered": int(hit.sum()), "recall": float(hit.mean()),
            "vru_reference": int(vru.sum()), "vru_recall": float(hit[vru].mean()) if vru.any() else float("nan")}
