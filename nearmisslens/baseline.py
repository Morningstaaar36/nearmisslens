"""B0, the bare model (validation/PREREG.md): Muse Spark watches 60 ten-second windows of the test clip and lists
near-misses with times and road-user types. Its events, and the pipeline's, are scored against the reference conflict
table at event level: same pair of road-user classes, times within 1 s, matched one to one."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from . import audit, video
from .cache import file_sha256, source_sha
from .config import ROOT, SETTINGS
from .cost import token_usd
from .meta_client import MetaClient, output_text
from .config import MODELS

MODEL = MODELS["reader"]
WINDOWS = 60
WINDOW_S = 10.0
CLIP_WIDTH = 1920
TOLERANCE_S = 1.0
CLASSES = ("vehicle", "two_wheeler", "pedestrian")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["near_misses"], "properties": {
    "near_misses": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["t_s", "road_user_1", "road_user_2", "description"],
        "properties": {"t_s": {"type": "number"}, "road_user_1": {"type": "string", "enum": list(CLASSES)},
                       "road_user_2": {"type": "string", "enum": list(CLASSES)}, "description": {"type": "string"}}}}}}
INSTRUCTIONS = (
    "You are watching a 10-second top-down drone video of a busy signalised intersection. List every near-miss: two "
    "road users that come within 1.5 seconds of colliding, either because one passes through a point the other "
    "reaches less than 1.5 seconds later, or because at their current speeds they would collide within 1.5 seconds. "
    "For each, give t_s, the time in seconds from the start of the video when they are closest, and the kind of each "
    "road user: vehicle (car, van, truck, bus, tricycle), two_wheeler (moped, scooter, motorcycle, bicycle) or "
    "pedestrian. Return an empty list if there are none.")


def ask(client: MetaClient, clip: Path, tag: str, clip_key: str | None = None) -> list[dict]:
    """clip_key identifies the clip by its source and cut, so the cache does not depend on encoder output bytes."""
    request = {"model": MODEL, "clip": clip_key or file_sha256(clip), "instructions": INSTRUCTIONS, "schema": SCHEMA}

    def run():
        return client.create_response({
            "model": MODEL, "instructions": INSTRUCTIONS, "reasoning": {"effort": "low"}, "max_output_tokens": 4000,
            "text": {"format": {"type": "json_schema", "name": "near_misses", "schema": SCHEMA, "strict": True}},
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_video", "file_id": client.upload_file(clip, expire_seconds=24 * 3600)}]}]})

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}

    resp = client.cached("b0", request, run, cost, 0.01, f"b0 {tag}", require_text=True)
    return json.loads(output_text(resp))["near_misses"]


def score(pred: pd.DataFrame, ref: pd.DataFrame, tol: float = TOLERANCE_S) -> dict:
    """One-to-one matching of events with the same unordered class pair and |dt| <= tol, minimising total |dt|."""
    key = lambda df: [tuple(sorted(p)) for p in zip(df["cls_1"], df["cls_2"])]
    tp = 0
    if len(pred) and len(ref):
        pk, rk = key(pred), key(ref)
        dt = np.abs(pred["t"].to_numpy(float)[:, None] - ref["t"].to_numpy(float)[None, :])
        ok = (dt <= tol) & np.array([[a == b for b in rk] for a in pk])
        cost = np.where(ok, dt, 1e6)
        rows, cols = linear_sum_assignment(cost)
        tp = int(ok[rows, cols].sum())
    p = tp / len(pred) if len(pred) else float("nan")
    r = tp / len(ref) if len(ref) else float("nan")
    f1 = 2 * p * r / (p + r) if len(pred) and len(ref) and p + r > 0 else (0.0 if len(ref) else float("nan"))
    return {"ref_events": int(len(ref)), "pred_events": int(len(pred)), "tp": tp, "precision": p, "recall": r, "f1": f1}


def windows(duration_s: float) -> list[float]:
    return [k * WINDOW_S for k in range(WINDOWS) if (k + 1) * WINDOW_S <= duration_s + 1e-6]


def estimate_usd() -> float:
    return WINDOWS * 0.01


def run_b0(client: MetaClient | None = None, split: str = "test") -> dict:
    from .runner import site_states
    client = client or MetaClient(SETTINGS)
    c, ref_states = site_states(split, "reference")
    span = len(windows(min(ref_states["t"].max(), WINDOWS * WINDOW_S))) * WINDOW_S
    ref = audit.conflict_table(ref_states)
    ref = ref[ref["t"] < span].reset_index(drop=True)
    client.check_budget(estimate_usd(), "b0")
    print(f"B0: {len(windows(span))} windows, up to ${estimate_usd():.2f} (cached calls are free)")
    work = SETTINGS.data_dir / "work" / "b0"
    rows = []
    for start in windows(span):
        clip = video.cut(c.video, work / f"{c.stem}_{start:.0f}.mp4", start, WINDOW_S, width=CLIP_WIDTH)
        key = f"{source_sha(c.video)}|{start}|{WINDOW_S}|{CLIP_WIDTH}"
        for e in ask(client, clip, f"{c.stem}@{start:.0f}", clip_key=key):
            rows.append({"t": start + min(max(float(e["t_s"]), 0.0), WINDOW_S), "cls_1": e["road_user_1"],
                         "cls_2": e["road_user_2"], "description": e["description"]})
    b0 = pd.DataFrame(rows, columns=["t", "cls_1", "cls_2", "description"])
    out = {"split": split, "clip": f"{c.site}_{c.stem}", "span_s": span, "tolerance_s": TOLERANCE_S,
           "b0": score(b0, ref)}
    try:
        _, ours = site_states(split, "sam", client)
        mine = audit.conflict_table(ours)
        out["pipeline"] = score(mine[mine["t"] < span], ref)
    except FileNotFoundError as e:
        out["pipeline"] = {"missing": f"{e}; run nml evaluate {split}"}
    dest = ROOT / "validation" / "results" / split
    dest.mkdir(parents=True, exist_ok=True)
    b0.to_csv(dest / "b0_events.csv", index=False)
    (dest / "b0.json").write_text(json.dumps(out, indent=1, default=float))
    return out
