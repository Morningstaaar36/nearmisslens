from __future__ import annotations

from pathlib import Path

from . import audit, countermeasures, evaluate, fluid, pipeline, video
from .config import SETTINGS
from .meta_client import MetaClient


def site_states(split: str, source: str, client: MetaClient | None = None):
    """Engine states for a split: FLUID reference trajectories, or SAM 3.1 tracks over the same frames."""
    site, limit_s = evaluate.SPLITS[split]
    c = fluid.clip(*site)
    info = video.probe(c.video)
    duration = info["frames"] / info["fps"]
    if limit_s:
        duration = min(duration, limit_s)
    frames = (1, int(round(duration * info["fps"])))
    if source == "reference":
        st = pipeline.reference_states(c, frames)
        return c, st[st["isReal"] == 1].reset_index(drop=True)
    from . import tracks
    points = pipeline.track_api(client or MetaClient(SETTINGS), c, 0.0, duration, evaluate.CONCEPTS,
                                SETTINGS.data_dir / "work" / split, pipeline.calibration_for(c))
    st = tracks.smooth_states(points, info["fps"])
    return c, st[st["frame"].between(*frames)].reset_index(drop=True)


def run_audit(split: str, source: str, out_root: Path | None = None) -> Path:
    c, states = site_states(split, source)
    signals = fluid.load_signals(c)
    facts = audit.audit(states, countermeasures.load_cmf(), signals=signals,
                        control="Signalized" if len(signals) else None,
                        right_turn_signalised=fluid.has_right_turn_control(signals))
    label = {"reference": "FLUID reference trajectories (YOLOv8-OBB + SparseTrack)",
             "sam": "SAM 3.1 tiled video tracking (Meta Model API)"}[source]
    out = (out_root or SETTINGS.runs_dir / "audit") / f"{split}_{source}"
    audit.write(facts, audit.memo(facts, f"{c.site} {c.stem}", label), out, audit.conflict_table(states))
    return out
