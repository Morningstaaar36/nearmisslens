"""Static data for the replay viewer (docs/, served by GitHub Pages): base map, audit facts, conflicts, the review
panel, signal state on entry and short trajectory windows around each hotspot's most severe conflicts.

Everything is read from an audit run and the same road-user states it used; nothing is computed in the browser
except drawing."""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from . import audit, calibrate, fluid, movements, runner
from .config import ROOT, SETTINGS, portable, resolve
from .meta_client import MetaClient

DOCS = ROOT / "docs" / "video"  # the drone-video replay viewer; docs/ itself is the copilot (nml pages)
MAP_WIDTH_PX = 2400
EVENTS_PER_HOTSPOT = 3
WINDOW_S = (-4.0, 3.0)
NEIGHBOUR_M = 35.0
REPLAY_HZ = 5.0
SOURCE_LABEL = {"reference": "FLUID reference trajectories (YOLOv8-OBB + SparseTrack)",
                "sam": "SAM 3.1 tiled video tracking (Meta Model API)"}


def base_map(c: fluid.Clip, out: Path, width_px: int = MAP_WIDTH_PX) -> dict:
    """Downscaled base map and its metric frame: x = x0 + col * mpp, y = y0 - row * mpp."""
    img = cv2.imread(str(c.base_map), cv2.IMREAD_COLOR)
    x0, y0, sx, sy = calibrate.geotiff_transform(c.base_map)
    f = width_px / img.shape[1]
    small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), small, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return {"image": out.name, "width": small.shape[1], "height": small.shape[0], "x0": x0, "y0": y0,
            "mpp_x": sx / f, "mpp_y": sy / f}


def event_window(states: pd.DataFrame, example: dict, x: float, y: float) -> dict:
    """Road users within NEIGHBOUR_M of the hotspot around one conflict, at REPLAY_HZ, times relative to the event."""
    t0 = example["t"]
    w = states[states["t"].between(t0 + WINDOW_S[0], t0 + WINDOW_S[1])]
    near = w.loc[np.hypot(w["x"] - x, w["y"] - y) <= NEIGHBOUR_M, "id"].astype(str).unique()
    w = w[w["id"].astype(str).isin(near)]
    step = max(1, int(round(1 / (REPLAY_HZ * w["t"].diff().replace(0, np.nan).abs().min())))) if len(w) > 1 else 1
    w = w[(w["frame"] % step) == 0]
    users = []
    for uid, tr in w.sort_values("t").groupby(w["id"].astype(str)):
        users.append({"id": uid, "cls": tr["cls"].iloc[0], "length": round(float(tr["length"].median()), 2),
                      "width": round(float(tr["width"].median()), 2),
                      "track": np.round(np.stack([tr["t"] - t0, tr["x"], tr["y"], tr["yaw"]], axis=1), 3).tolist()})
    return {**example, "users": users}


def signal_entry(states: pd.DataFrame, signals: pd.DataFrame, classes=("vehicle", "two_wheeler")) -> list[dict]:
    """Signal state on entry per approach and road-user class, for users whose movement has a signal group."""
    r = movements.routes(states)
    r = r[r["cls"].isin(classes)]
    r = r.assign(state=[movements.entry_signal(signals, x) for x in r.itertuples()]).dropna(subset=["state"])
    if r.empty:
        return []
    counts = r.groupby(["entry_arm", "cls", "state"]).size().unstack(fill_value=0)
    return [{"arm": arm, "cls": cls, **{s: int(counts.loc[(arm, cls)].get(s, 0)) for s in ("G", "y", "r")}}
            for arm, cls in counts.index]


def selftest_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        m = re.match(r"^\| (\w+) \| (PASS|FAIL|SKIP) \| (.*) \| `(.*)` \|$", line)
        if m:
            rows.append({"check": m[1], "status": m[2], "criterion": m[3], "result": json.loads(m[4])})
    return rows


def current(path: Path, facts_id: str) -> dict | None:
    """A review stored next to an audit, if it reviewed this version of the audit's facts."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("facts_id") != facts_id:
        print(f"skipping {path.name}: it reviewed an earlier version of this audit; run it again")
        return None
    return data


def panel_view(p: dict | None) -> dict | None:
    if p is None:
        return None
    keep = ("status", "proposals", "objections", "decisions", "memo", "usd", "caught")
    return {**{k: p[k] for k in keep if k in p},
            "stages": [{k: s[k] for k in ("role", "model", "accepted", "stopped", "turns", "usd")}
                       | {"caught": [e for a in s["rejected_attempts"] for e in a["errors"]]} for s in p["stages"]]}


def _media(src: str | None, out_dir: Path) -> str | None:
    """Copy an image for the viewer, as a JPEG at the original size."""
    src = resolve(src) if src else None
    if not src or not src.exists():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{src.stem}.jpg"
    cv2.imwrite(str(out_dir / name), cv2.imread(str(src)), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return f"media/{name}"


def office_view(path: Path) -> dict | None:
    """The manager run as a mission-control timeline: reasoning summaries, tool calls with timings, refusals, sign-off
    and the accepted work order (tool results are trimmed to what the viewer shows)."""
    if not path.exists():
        return None
    o = json.loads(path.read_text())
    tl = []
    for e in o.get("timeline", []):
        if e["kind"] == "thought":
            tl.append({"turn": e["turn"], "kind": "thought", "text": e["text"][:600]})
        else:
            res = e.get("result") or {}
            tl.append({"turn": e["turn"], "kind": "tool", "tool": e["tool"], "arguments": e["arguments"],
                       "seconds": e.get("seconds"), "error": res.get("error"), "errors": res.get("errors", [])[:4]})
    return {"turns": o.get("turns"), "usd": o.get("usd"), "refusals": o.get("refusals"), "stopped": o.get("stopped"),
            "signoffs": o.get("signoffs"), "work_order": o.get("work_order"), "complaints": o.get("complaints"),
            "timeline": tl}


def context_view(path: Path) -> list[dict]:
    """The demo junctions' city-context dossiers and memos (NML-Bench T8)."""
    if not path.exists():
        return []
    rows = json.loads(path.read_text())["rows"]
    return [{k: r.get(k) for k in ("name", "city", "lat", "lon", "plan_gap", "designated", "injury_crashes")}
            | {"memo": (r.get("checked") or {}).get("memo")} for r in rows if r.get("group") == "demo"]


def export(split: str, source: str, docs: Path = DOCS, client: MetaClient | None = None) -> Path:
    run = SETTINGS.runs_dir / "audit" / f"{split}_{source}"
    if not (run / "facts.json").exists():
        raise FileNotFoundError(f"no audit at {run}; run: nml audit {split} --source {source}")
    facts_json = (run / "facts.json").read_text()
    facts = json.loads(facts_json)
    fid = audit.facts_id(facts_json)
    c, states = runner.site_states(split, source, client)
    key = f"{split}_{source}"
    data = docs / "data"
    signals = fluid.load_signals(c)
    for f in facts["findings"]:
        f["replays"] = [event_window(states, e, f["x"], f["y"]) for e in f["examples"][:EVENTS_PER_HOTSPOT]]
        if f.get("illustration"):
            f["illustration"]["image"] = _media(f["illustration"]["image"], data / "media")
    conflicts = pd.read_csv(run / "conflicts.csv") if (run / "conflicts.csv").exists() else pd.DataFrame()
    view = {"key": key, "split": split, "site": c.site, "clip": c.stem, "source": SOURCE_LABEL[source],
            "map": base_map(c, data / "media" / f"{c.site}_map.jpg"), "facts": facts,
            "memo": (run / "memo.md").read_text(), "panel": panel_view(current(run / "panel.json", fid)),
            "conflicts": conflicts[["measure", "value", "type", "cls_1", "cls_2", "t", "x", "y"]].round(2).to_dict("list")
            if len(conflicts) else {}, "signal_entry": signal_entry(states, signals, facts.get("signal_evidence_classes", audit.SIGNAL_CLASSES)),
            "voice": current(run / "voice.json", fid), "office": office_view(run / "office.json")}
    data.mkdir(parents=True, exist_ok=True)
    (data / f"{key}.json").write_text(portable(json.dumps(view, separators=(",", ":"), default=float)))
    index_path = data / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"audits": []}
    index["audits"] = sorted([a for a in index["audits"] if a["key"] != key]
                             + [{"key": key, "title": f"{c.site} {c.stem} ({split}, {source})"}], key=lambda a: a["key"])
    index["selftest"] = selftest_rows(ROOT / "validation" / "SELFTEST.md")
    results = ROOT / "validation" / "RESULTS.md"
    index["results_md"] = results.read_text() if results.exists() else None
    bench_md = ROOT / "validation" / "BENCH.md"
    index["bench_md"] = bench_md.read_text() if bench_md.exists() else None
    index["context"] = context_view(ROOT / "validation" / "results" / "bench" / "context.json")
    index_path.write_text(json.dumps(index, indent=1))
    return data / f"{key}.json"
