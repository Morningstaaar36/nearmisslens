"""NML-Bench tasks computed from FLUID reference trajectories over every flight ($0), as registered in
validation/BENCH_PREREG.md: T3 hotspot persistence and T7 fix test with a random control."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

from . import audit, conflicts, fluid, movements, pipeline, risk
from .config import SETTINGS
from .evaluate import RESULTS_DIR

BENCH_DIR = RESULTS_DIR / "bench"
SEED = 0
FLUID_FPS = 10.0


def _work() -> Path:
    p = Path(SETTINGS.data_dir) / "work" / "bench"
    p.mkdir(parents=True, exist_ok=True)
    return p


def flight_states(site: str, stem: str) -> tuple[fluid.Clip, pd.DataFrame]:
    """Reference engine states for a whole flight (real detections only)."""
    c = fluid.clip(site, stem)
    raw = fluid.load_trajectories(c)
    # FLUID videos are all down-sampled to 10 fps (FLUID README), so the video is not needed for reference states.
    fps = pipeline.clip_fps(c) if c.video.exists() else FLUID_FPS
    st = conflicts.from_fluid(raw, fps).merge(raw[["id", "frame", "speed", "isReal"]], on=["id", "frame"])
    return c, st[st["isReal"] == 1].reset_index(drop=True)


def flight_conflicts(site: str, stem: str, states: pd.DataFrame | None = None) -> pd.DataFrame:
    """The audit's conflict table (PET <= 1.5 s or TTC <= 1.5 s) for a whole flight, cached on disk."""
    out = _work() / f"{site}_{stem}_conflicts.csv.gz"
    if out.exists():
        return pd.read_csv(out)
    if states is None:
        _, states = flight_states(site, stem)
    table = audit.conflict_table(states)
    table.to_csv(out, index=False)
    return table


def cell_rates(table: pd.DataFrame, states: pd.DataFrame, cell_m: float = audit.CELL_M) -> pd.DataFrame:
    """Conflicts per 1,000 road users per cell, for every cell that road users pass through."""
    users = states.assign(cx=np.floor(states["x"] / cell_m), cy=np.floor(states["y"] / cell_m)) \
        .groupby(["cx", "cy"])["id"].nunique().rename("users")
    ev = table.assign(cx=np.floor(table["x"] / cell_m), cy=np.floor(table["y"] / cell_m)) \
        .groupby(["cx", "cy"]).size().rename("events")
    h = pd.concat([users, ev], axis=1).fillna({"events": 0}).dropna(subset=["users"])
    h["rate"] = 1000 * h["events"] / h["users"]
    return h


def _ranking(table: pd.DataFrame, states: pd.DataFrame) -> list[tuple]:
    h = risk.hotspots(table, states, cell_m=audit.CELL_M, min_events=audit.MIN_HOTSPOT_EVENTS)
    h = h.sort_values(["ci_low", "events"], ascending=False)
    return [(np.floor(x / audit.CELL_M), np.floor(y / audit.CELL_M)) for x, y in zip(h["cx"], h["cy"])]


def persistence(flights=fluid.FLIGHTS, permutations: int = 1000) -> dict:
    """T3: Kendall tau-b of cell conflict rates and top-3 overlap for every pair of flights at the same site, with a
    shuffled-cell null."""
    rng = np.random.default_rng(SEED)
    per = {}
    for site, stem in flights:
        c, st = flight_states(site, stem)
        if st.empty:
            continue
        table = flight_conflicts(site, stem, st)
        per[(site, stem)] = {"rates": cell_rates(table, st), "top": _ranking(table, st)[:3],
                             "day": stem.split("_")[0], "events": len(table), "minutes": float(st["t"].max() - st["t"].min()) / 60}
    pairs = []
    for (a, b) in itertools.combinations(per, 2):
        if a[0] != b[0]:
            continue
        ra, rb = per[a]["rates"], per[b]["rates"]
        cells = ra.index.union(rb.index)
        cells = [k for k in cells if ra["events"].get(k, 0) + rb["events"].get(k, 0) > 0]
        x = np.array([ra["rate"].get(k, 0.0) for k in cells])
        y = np.array([rb["rate"].get(k, 0.0) for k in cells])
        tau = kendalltau(x, y).statistic if len(cells) > 2 else float("nan")
        null = np.array([kendalltau(x, rng.permutation(y)).statistic for _ in range(permutations)])
        top = len(set(per[a]["top"]) & set(per[b]["top"]))
        pairs.append({"site": a[0], "a": a[1], "b": b[1], "different_day": per[a]["day"] != per[b]["day"],
                      "cells": len(cells), "tau": float(tau), "p_perm": float((np.sum(null >= tau) + 1) / (permutations + 1)),
                      "top3_overlap": top, "null_tau_mean": float(np.nanmean(null))})
    df = pd.DataFrame(pairs)
    diff = df[df["different_day"]] if len(df) else df
    # pooled one-sided test: is the mean tau over different-day pairs above the mean of shuffled taus?
    pooled_p = None
    if len(diff):
        obs = diff["tau"].mean()
        sims = []
        for _ in range(permutations):
            sims.append(np.mean([kendalltau(
                np.array([per[(r.site, r.a)]["rates"]["rate"].get(k, 0.0) for k in _cells(per, r)]),
                rng.permutation(np.array([per[(r.site, r.b)]["rates"]["rate"].get(k, 0.0) for k in _cells(per, r)]))
            ).statistic for r in diff.itertuples()]))
        pooled_p = float((np.sum(np.array(sims) >= obs) + 1) / (permutations + 1))
    out = {"flights": [{"site": s, "flight": f, "conflicts": v["events"], "minutes": round(v["minutes"], 1)}
                       for (s, f), v in per.items()],
           "pairs": pairs,
           "summary": {"pairs": len(df), "different_day_pairs": int(len(diff)),
                       "median_tau_different_day": float(diff["tau"].median()) if len(diff) else None,
                       "median_tau_all": float(df["tau"].median()) if len(df) else None,
                       "mean_top3_overlap_different_day": float(diff["top3_overlap"].mean()) if len(diff) else None,
                       "pooled_p_different_day": pooled_p,
                       "claim": bool(len(diff) and diff["tau"].median() > 0 and pooled_p is not None and pooled_p < 0.05)}}
    _write("persistence.json", out)
    return out


def _cells(per: dict, r) -> list:
    ra, rb = per[(r.site, r.a)]["rates"], per[(r.site, r.b)]["rates"]
    return [k for k in ra.index.union(rb.index) if ra["events"].get(k, 0) + rb["events"].get(k, 0) > 0]


def red_entries(c: fluid.Clip, states: pd.DataFrame, classes=("vehicle", "two_wheeler")) -> list:
    """Road users of the given classes whose entry into the junction was on red."""
    sig = fluid.load_signals(c)
    r = movements.routes(states)
    r = r[r["cls"].isin(classes)]
    return [x.id for x in r.itertuples() if movements.entry_signal(sig, x) == "r"]


def fix_test(flights=fluid.FLIGHTS, draws: int = 200) -> dict:
    """T7: conflicts removed when every red-light entrant is removed, against removing the same number of random
    non-red road users of the same classes. An upper bound on conflicts in edited trajectories, not crashes avoided."""
    rng = np.random.default_rng(SEED)
    rows = []
    for site, stem in flights:
        c, st = flight_states(site, stem)
        if st.empty:
            continue
        table = flight_conflicts(site, stem, st)
        red = set(map(str, red_entries(c, st)))
        if not red:
            rows.append({"site": site, "flight": stem, "red_entrants": 0, "conflicts": len(table)})
            continue
        ids1, ids2 = table["id_1"].astype(str), table["id_2"].astype(str)
        removed = int((ids1.isin(red) | ids2.isin(red)).sum())
        cls_of = st.groupby("id")["cls"].first()
        cls_of.index = cls_of.index.astype(str)
        pool = {k: [i for i in cls_of.index[cls_of == k] if i not in red] for k in ("vehicle", "two_wheeler")}
        need = pd.Series([cls_of.get(i) for i in red]).value_counts().to_dict()
        ctrl = []
        for _ in range(draws):
            pick = set()
            for k, n in need.items():
                cand = pool.get(k, [])
                pick |= set(rng.choice(cand, size=min(n, len(cand)), replace=False)) if cand else set()
            ctrl.append(int((ids1.isin(pick) | ids2.isin(pick)).sum()))
        ctrl = np.array(ctrl)
        rows.append({"site": site, "flight": stem, "red_entrants": len(red), "conflicts": len(table),
                     "removed_targeted": removed, "control_median": float(np.median(ctrl)),
                     "control_p95": float(np.percentile(ctrl, 95)),
                     "percentile": float((ctrl < removed).mean() * 100), "control": ctrl.tolist()})
    df = pd.DataFrame([r for r in rows if "removed_targeted" in r])
    summary = {}
    if len(df):
        pooled_ctrl = np.sum(np.array(df["control"].tolist()), axis=0)
        pooled = int(df["removed_targeted"].sum())
        summary = {"flights": len(df), "red_entrants": int(df["red_entrants"].sum()),
                   "conflicts": int(df["conflicts"].sum()), "removed_targeted": pooled,
                   "removed_share": pooled / max(int(df["conflicts"].sum()), 1),
                   "control_median": float(np.median(pooled_ctrl)), "control_p95": float(np.percentile(pooled_ctrl, 95)),
                   "ratio_to_control_median": pooled / max(float(np.median(pooled_ctrl)), 1e-9),
                   "claim": bool(pooled > np.percentile(pooled_ctrl, 95))}
    out = {"per_flight": [{k: v for k, v in r.items() if k != "control"} for r in rows], "summary": summary}
    _write("fix_test.json", out)
    return out


def _write(name: str, obj: dict) -> None:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / name).write_text(json.dumps(obj, indent=1, default=float))


def fresh_estimate() -> float:
    """SAM 3.1 cost of tracking every registered fresh window (PREREG change 11), before any call."""
    from . import tiling, windows
    from .evaluate import CONCEPTS
    frames = int(windows.DURATION_S * FLUID_FPS)
    return len(windows.FRESH) * tiling.estimate_usd(frames, 4, len(CONCEPTS))


def _pooled(rows: list[dict], key: str) -> dict:
    tp = sum(r[key]["tp"] for r in rows)
    ref = sum(r[key]["ref_events"] for r in rows)
    pred = sum(r[key]["pred_events"] for r in rows)
    p = tp / pred if pred else float("nan")
    r = tp / ref if ref else float("nan")
    f1 = 2 * p * r / (p + r) if pred and ref and (p + r) else 0.0
    from .evaluate import f2
    return {"tp": tp, "ref_events": ref, "pred_events": pred, "precision": p, "recall": r, "f1": f1,
            "f2": f2({"tp": tp, "ref_events": ref, "pred_events": pred})}


def _bootstrap_f1_diff(per: list[dict], key: str, n: int = 2000) -> list[float]:
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(n):
        idx = rng.integers(0, len(per), len(per))
        a = _pooled([per[i]["v0"] for i in idx], key)["f1"]
        b = _pooled([per[i]["v1"] for i in idx], key)["f1"]
        diffs.append(b - a)
    return [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]


def fresh_flights(client, flights=None) -> dict:
    """PREREG change 11: track each fresh window with SAM 3.1 (cached after the first run), then score v0
    (Savitzky-Golay) and v1 (Kalman/RTS chosen on dev) on the same stitched tracks against the reference."""
    from . import evaluate, tracks, windows
    from .evaluate import CONCEPTS, chosen_kinematics
    kin = chosen_kinematics()
    per = []
    for site, stem in flights or windows.FRESH:
        wc = windows.window_clip(site, stem)
        if not wc.video.exists():
            windows.cut(site, stem)
        cal = pipeline.calibration_for(wc)
        pts = pipeline.track_api(client, wc, 0.0, windows.DURATION_S, CONCEPTS, Path(SETTINGS.data_dir) / "work" / "fresh",
                                 cal)
        if pts.empty:
            continue
        pts = pts.assign(frame=pts["frame"] + windows.FRAME_OFFSET)
        pts["t"] = pts["frame"] / FLUID_FPS
        frames = (windows.FRAME_OFFSET + 1, windows.FRAME_OFFSET + int(windows.DURATION_S * FLUID_FPS))
        row = {"site": site, "flight": stem, "smoke": windows.smoke(site, stem)}
        for name, k in (("v0", None), ("v1", kin)):
            ours, ref, trk = evaluate.evaluate_tracks(pts, wc, frames, f"fresh {site} {stem} {name}", stitch=True,
                                                      kinematics=k)
            res = evaluate.evaluate_conflicts(ours, ref, f"fresh {site} {stem} {name}")
            s = res["summary"]
            tracked = res["ref"][~((res["ref"]["cls_1"] == "pedestrian") | (res["ref"]["cls_2"] == "pedestrian"))]
            sub = evaluate.match.event_metrics(res["ours"], tracked, res["map"])
            row[name] = {"tracking": trk, "ttc": s["all"], "pet<=1.5": s["pet<=1.5"], "pet<=3.0": s["pet<=3.0"],
                         "ttc_tracked_classes": sub}
        per.append(row)
    out = {"window_s": [windows.START_S, windows.START_S + windows.DURATION_S], "flights": per}
    if per:
        out["pooled"] = {v: {k: _pooled([r[v] for r in per], k) for k in ("ttc", "pet<=1.5", "ttc_tracked_classes")}
                         for v in ("v0", "v1")}
        ci = _bootstrap_f1_diff(per, "ttc")
        out["ttc_f1_diff_ci95"] = ci
        ok = [r for r in per if r["smoke"]["pass"]]
        if ok and len(ok) < len(per):  # secondary: windows whose calibration passes the 0.6 m check
            out["pooled_calibration_ok"] = {v: {k: _pooled([r[v] for r in ok], k) for k in ("ttc", "pet<=1.5")}
                                            for v in ("v0", "v1")}
            out["calibration_ok_flights"] = len(ok)
        out["claim_v1_better"] = bool(out["pooled"]["v1"]["ttc"]["f1"] > out["pooled"]["v0"]["ttc"]["f1"] and ci[0] > 0)
    _write("fresh.json", out)
    return out


AUDITS = ("test_sam", "heldout_sam")
T4_ARMS = (("spark_checked", "muse-spark-1.3-contributor", True, 0.02),
           ("spark_unchecked", "muse-spark-1.3-contributor", False, 0.02),
           ("wonder_checked", "muse-wonder-1.0", True, 0.12))


def _score_complaint(verdict: str, rank: int | None, exp_verdict: str, exp_ranks: set) -> dict:
    ok_verdict = verdict == exp_verdict
    ok = ok_verdict and (verdict != "supported" or (rank in exp_ranks))
    return {"verdict_ok": ok_verdict, "correct": ok}


def complaints_bench(client) -> dict:
    """T4: every benchmark complaint for both SAM audits, answered by the fixed rule (Muse Spark extraction + rule), and
    by the intake agent on Muse Spark Contributor with and without the checker and on Muse Wonder with the checker."""
    from . import ask, complaints, voice
    from .countermeasures import load_cmf
    cmf = load_cmf()
    rows = []
    for a in AUDITS:
        facts, memo_md = ask.load(a, SETTINGS.runs_dir)
        frames = Path(SETTINGS.data_dir) / "work" / "ask_frames"
        for k, c in enumerate(complaints.benchmark_set(facts)):
            exp_v, exp_r = ask.truth(c, facts)
            base = {"audit": a, "kind": c["kind"], "lang": c["lang"], "text": c["text"], "expected": exp_v,
                    "expected_ranks": sorted(exp_r)}
            ext = voice.extract(client, c["text"], f"t4 {a} {k}")
            m = voice.match(ext, facts)
            v = "unclear" if not ext["road_users"] else ("supported" if m["rank"] else "not_observed")
            rows.append({**base, "method": "fixed_rule", "verdict": v, "rank": m["rank"], "errors": [], "usd": None,
                         **_score_complaint(v, m["rank"], exp_v, exp_r)})
            for arm, model, checked, budget in T4_ARMS:
                out = ask.answer(client, c["text"], facts, memo_md, cmf, frames, f"t4 {a} {k} {arm}", checked=checked,
                                 model=model, budget_usd=budget)
                r = out["result"] or {"verdict": "none", "rank": None, "errors": ["no answer"]}
                rows.append({**base, "method": arm, "verdict": r["verdict"], "rank": r.get("rank"),
                             "errors": r.get("errors", []), "usd": out["usd"], "turns": out["turns"],
                             "refusals": out["refusals"], "stopped": out["stopped"], "answer": r.get("answer"),
                             **_score_complaint(r["verdict"], r.get("rank"), exp_v, exp_r)})
    df = pd.DataFrame(rows)
    summary = {}
    for mth, g in df.groupby("method"):
        summary[mth] = {"n": len(g), "accuracy": float(g["correct"].mean()), "verdict_accuracy": float(g["verdict_ok"].mean()),
                        "ungrounded_answers": int((g["errors"].map(len) > 0).sum()),
                        "usd_total": float(g["usd"].fillna(0).sum()),
                        "usd_per_complaint": float(g["usd"].fillna(0).mean())}
        for kind, gk in g.groupby("kind"):
            summary[mth][f"accuracy_{kind}"] = float(gk["correct"].mean())
    out = {"rows": rows, "summary": summary}
    _write("complaints.json", out)
    return out


def panel_ablation(client) -> dict:
    """T5: the review panel on both SAM audits without the checker; ungrounded items counted by the same checker,
    next to the stored checked runs (panel.json)."""
    from . import panel
    from .countermeasures import load_cmf
    cmf = load_cmf()
    out = {}
    for a in AUDITS:
        src = SETTINGS.runs_dir / "audit" / a
        facts, memo_md = json.loads((src / "facts.json").read_text()), (src / "memo.md").read_text()
        res = panel.run_panel(client, facts, memo_md, cmf, f"t5 {a} unchecked", checked=False)
        stored = json.loads((src / "panel.json").read_text())
        out[a] = {"unchecked": {"status": res["status"], "ungrounded_items": sum(len(s.get("ungrounded", []))
                                                                              for s in res["stages"]),
                                "ungrounded": [e for s in res["stages"] for e in s.get("ungrounded", [])],
                                "usd": round(sum(s["usd"] for s in res["stages"]), 4)},
                  "checked": {"status": stored["status"], "caught": stored.get("caught", 0),
                              "usd": stored.get("usd")}}
    _write("panel_ablation.json", out)
    return out


T8_JUNCTIONS = Path(__file__).resolve().parent / "data" / "t8_junctions.json"


def context_bench(client, arms=(True, False)) -> dict:
    """T8: dossiers for the registered junction list (open data, $0) and Muse Spark memos with and without the fact
    checker; retrieval success and latency per source, ungrounded numbers per memo, cost per dossier."""
    from . import context
    js = json.loads(T8_JUNCTIONS.read_text())
    rows = []
    for j in js["junctions"]:
        d = context.dossier(j["lat"], j["lon"])
        ok = {s: isinstance(d.get(s), dict) and "error" not in d[s] for s in ("street", "crashes", "plans")}
        row = {**j, "sources_ok": ok, "plan_gap": d.get("plan_gap"),
               "designated": (d.get("plans") or {}).get("designated"),
               "injury_crashes": (d.get("crashes") or {}).get("injury_crashes")}
        for checked in arms:
            m = context.memo(client, d, f"t8 {j['id']} {'checked' if checked else 'unchecked'}", checked=checked)
            row["checked" if checked else "unchecked"] = {"errors": m["errors"], "usd": m["usd"], "attempts": m["attempts"],
                                                          "memo": m["memo"]}
        rows.append(row)
    df = pd.DataFrame(rows)
    summary = {"junctions": len(df),
               "source_success": {s: float(np.mean([r["sources_ok"][s] for r in rows])) for s in ("street", "crashes", "plans")},
               "plan_gaps": int(sum(bool(r["plan_gap"]) for r in rows)),
               "designated": int(sum(bool(r["designated"]) for r in rows))}
    for arm in ("checked", "unchecked"):
        if arm in df:
            summary[arm] = {"memos_with_ungrounded_numbers": int(sum(bool(r[arm]["errors"]) for r in rows)),
                            "usd_per_memo": float(np.mean([r[arm]["usd"] for r in rows]))}
    out = {"rows": rows, "summary": summary}
    _write("context.json", out)
    return out


T6_SAM_USD, T6_AGENT_USD = 1.0, 1.0


def conductor_bench(client, sam_usd: float = T6_SAM_USD, agent_usd: float = T6_AGENT_USD) -> dict:
    """T6 (registered in PREREG): uniform, greedy (motion energy) and the Muse Wonder conductor each spend the same SAM
    budget on the held-out clip; scored by the share of reference TTC events whose two users are tracked at the event
    frame, and per dollar."""
    from . import conductor, conflicts
    from .evaluate import SPLITS
    c = fluid.clip(*SPLITS["heldout"][0])
    cal = pipeline.calibration_for(c)
    site = conductor.make_site(c, cal, Path(SETTINGS.data_dir) / "work" / "conductor")
    ref = pipeline.reference_states(c, (1, int(round(site.duration_s * site.fps))))
    ref = ref[ref["isReal"] == 1]
    ref_ev = conflicts.ttc_events(ref[conflicts.STATE_COLUMNS])
    out = {"clip": f"{c.site}_{c.stem}", "sam_budget_usd": sam_usd, "policies": {}}
    for name, fn in (("uniform", conductor.policy_uniform), ("greedy", conductor.policy_greedy)):
        led = fn(client, site, sam_usd)
        out["policies"][name] = conductor.conflict_recall(site, led, ref_ev, ref)
    led, info = conductor.policy_agent(client, site, sam_usd, agent_budget_usd=agent_usd, max_turns=30)
    out["policies"]["wonder_agent"] = {**conductor.conflict_recall(site, led, ref_ev, ref),
                                       "agent_usd": round(info["agent_usd"], 4), "turns": info["turns"],
                                       "stopped": info["stopped"], "jobs_chosen": [list(j) for j in led.jobs]}
    for p in out["policies"].values():
        total = p["spent_usd"] + p.get("agent_usd", 0.0)
        p["recovered_per_usd"] = p["recovered"] / total if total else None
    out["decision_log"] = info["decision_log"]
    _write("conductor.json", out)
    return out


def _f(v, d=3):
    return f"{v:.{d}f}" if isinstance(v, (int, float)) and v == v else "n/a"


def cost_per_junction_hour() -> dict:
    """Measured Meta API cost of the fresh-window audits, per hour of 4K video, by model (from the spend ledger)."""
    led = [json.loads(l) for l in Path(SETTINGS.ledger).read_text().splitlines() if l.strip()]
    from . import windows
    stems = {f"{stem}@" for _, stem in windows.FRESH}
    sam = sum(r["usd"] for r in led if r.get("model") == "sam-3.1" and any(s in r.get("what", "") for s in stems))
    fr = _load("fresh.json")
    if not fr:
        raise FileNotFoundError("fresh flights not scored yet")
    minutes = len(fr["flights"]) * windows.DURATION_S / 60
    return {"sam_usd": round(sam, 3), "minutes": minutes, "sam_usd_per_hour": round(sam / minutes * 60, 2) if minutes else None}


def write_bench_md() -> str:
    L = ["# NML-Bench results", "",
         "Generated by `nml bench --report` from `validation/results/`. Registered in `BENCH_PREREG.md` and `PREREG.md` "
         "changes 10–11. Agreement is with FLUID reference trajectories (a trained YOLOv8-OBB + SparseTrack pipeline), "
         "not ground truth.", ""]
    fr = _load("fresh.json")
    if fr and fr.get("pooled"):
        L += ["## T1–T2 Fresh flights (11 one-minute windows, 2 new days and a third junction, never seen before)", "",
              "| pipeline | conflict set | reference | ours | matched | precision | recall | F1 | F2 |", "|---|---|---|---|---|---|---|---|---|"]
        for v, label in (("v0", "v0 Savitzky–Golay (registered)"), ("v1", "v1 Kalman/RTS (change 10)")):
            for k in ("ttc", "pet<=1.5", "ttc_tracked_classes"):
                m = fr["pooled"][v][k]
                L.append(f"| {label} | {k} | {m['ref_events']} | {m['pred_events']} | {m['tp']} | {_f(m['precision'])} | "
                         f"{_f(m['recall'])} | {_f(m['f1'])} | {_f(m['f2'])} |")
        ci = fr.get("ttc_f1_diff_ci95")
        L += ["", f"TTC F1 difference v1 − v0, 95% bootstrap over flights: [{_f(ci[0])}, {_f(ci[1])}]. "
                  f"Registered rule met: {'yes' if fr.get('claim_v1_better') else 'no'}.", ""]
        if fr.get("pooled_calibration_ok"):
            pc = fr["pooled_calibration_ok"]
            L += [f"Secondary (decided after tracking, before scoring): the {fr['calibration_ok_flights']} windows whose "
                  "calibration passes the 0.6 m check (two TI windows reproject at about 1 m): "
                  + "; ".join(f"{v} TTC F1 {_f(pc[v]['ttc']['f1'])}, PET ≤ 1.5 s F1 {_f(pc[v]['pet<=1.5']['f1'])}"
                              for v in ("v0", "v1")) + ".", ""]
        L += ["Tracking per flight (v1, vehicle and two-wheeler recall / IDF1) and the free pre-tracking checks:", "",
              "| flight | calibration median (m) | vehicle recall | vehicle IDF1 | two-wheeler recall | two-wheeler IDF1 |",
              "|---|---|---|---|---|---|"]
        for r in fr["flights"]:
            t = {x["class"]: x for x in r["v1"]["tracking"]}
            g = lambda c, k: _f(t.get(c, {}).get(k))
            L.append(f"| {r['site']} {r['flight']} | {_f(r['smoke']['calibration_median_m'], 2)} | {g('vehicle', 'recall')} | {g('vehicle', 'idf1')} | "
                     f"{g('two_wheeler', 'recall')} | {g('two_wheeler', 'idf1')} |")
        L.append("")
    p = _load("persistence.json")
    if p:
        s = p["summary"]
        L += ["## T3 Hotspot persistence across days (reference trajectories, all 14 flights)", "",
              f"{s['pairs']} flight pairs at the same junction, {s['different_day_pairs']} on different days. Median Kendall "
              f"tau (different days) {_f(s['median_tau_different_day'])}; mean top-3 overlap {_f(s['mean_top3_overlap_different_day'], 2)} "
              f"of 3; pooled permutation p = {_f(s['pooled_p_different_day'], 4)}. Claim \"hotspots persist\": "
              f"{'yes' if s['claim'] else 'no'}.", ""]
    t = _load("fix_test.json")
    if t and t.get("summary"):
        s = t["summary"]
        L += ["## T7 Fix test with a random control (reference trajectories, all 14 flights)", "",
              f"Removing the {s['red_entrants']} road users who entered on red removes {s['removed_targeted']} of "
              f"{s['conflicts']} conflicts ({_f(100 * s['removed_share'], 1)}%). Removing the same number of random road users "
              f"of the same classes removes a median of {_f(s['control_median'], 0)} (95th percentile {_f(s['control_p95'], 0)}): "
              f"{_f(s['ratio_to_control_median'], 2)}× the control. An upper bound on conflicts in edited trajectories, not crashes avoided.", ""]
    c = _load("complaints.json")
    if c:
        L += ["## T4 Complaint verification (32 complaints on the two SAM audits)", "",
              "| method | accuracy | full | users only | other approach | absent pair | vague | answers with ungrounded claims | cost per complaint |",
              "|---|---|---|---|---|---|---|---|---|"]
        for m, s in c["summary"].items():
            L.append(f"| {m} | {_f(s['accuracy'])} | {_f(s.get('accuracy_full'))} | {_f(s.get('accuracy_users_only'))} | "
                     f"{_f(s.get('accuracy_other_approach'))} | {_f(s.get('accuracy_absent_pair'))} | {_f(s.get('accuracy_vague'))} | "
                     f"{s.get('ungrounded_answers_rescored', s['ungrounded_answers'])} | "
                     + ("Modal GPU time |" if m.startswith("glimmer") else f"${_f(s['usd_per_complaint'], 4)} |"))
        L += ["", "Ungrounded claims are counted with the checker that reads decimal commas (\"185,7\"). The first run's "
              "checker misread them: it flagged one Spanish and one French answer as ungrounded, and on one complaint "
              "Muse Wonder spent its budget correcting a correct number (post-hoc fix, disclosed). Wonder's one "
              "remaining miss answered \"not observed\" for a hotspot where Muse Spark's video review had judged 0 of 3 "
              "conflicts real; the label ignores the video review.", ""]
    pa = _load("panel_ablation.json")
    if pa:
        L += ["## T5 Grounding: review panel with and without the checker", "", "| audit | with checker: claims caught | without checker: ungrounded items in the accepted output |", "|---|---|---|"]
        for a, r in pa.items():
            L.append(f"| {a} | {r['checked']['caught']} | {r['unchecked']['ungrounded_items']} |")
        L.append("")
    co = _load("conductor.json")
    if co:
        L += [f"## T6 Budgeted perception on the held-out site (${co['sam_budget_usd']:.2f} SAM per policy)", "",
              "| policy | jobs | SAM spent | agent cost | reference TTC events covered | recall | VRU recall | covered per $ |", "|---|---|---|---|---|---|---|---|"]
        for n, r in co["policies"].items():
            L.append(f"| {n} | {r['jobs']} | ${_f(r['spent_usd'], 2)} | ${_f(r.get('agent_usd', 0.0), 2)} | {r['recovered']} of {r['reference']} | "
                     f"{_f(r['recall'])} | {_f(r['vru_recall'])} | {_f(r['recovered_per_usd'], 1)} |")
        L.append("")
    ctx = _load("context.json")
    if ctx:
        s = ctx["summary"]
        L += [f"## T8 City context ({s['junctions']} junctions in NYC, DC, Chicago, LA; open data only)", "",
              f"Source success: street {_f(s['source_success']['street'], 2)}, crashes {_f(s['source_success']['crashes'], 2)}, "
              f"plans {_f(s['source_success']['plans'], 2)}. Plan gaps found: {s['plan_gaps']}; designated by the city: {s['designated']}.", ""]
        for arm in ("checked", "unchecked", "open_checked", "glimmer_checked"):
            if arm in s:
                n = s[arm].get("memos_with_ungrounded_numbers_rescored", s[arm]["memos_with_ungrounded_numbers"])
                who = {"checked": "Muse Spark memos with the fact checker", "unchecked": "Muse Spark memos without the fact checker",
                       "open_checked": "Muse Spark Open (Baseten) memos with the fact checker",
                       "glimmer_checked": "Muse Glimmer (Modal GPU) memos with the fact checker"}[arm]
                cost = "paid by Modal GPU time (one L4)" if arm.startswith("glimmer") else f"${_f(s[arm]['usd_per_memo'], 5)} per memo"
                L.append(f"- {who}: {n} of {s['junctions']} contain a number that is not in the dossier; {cost}.")
        groups = {}
        for r in ctx["rows"]:
            groups.setdefault(r["group"], []).append(r)
        L += ["", "| junctions | n | on the city's priority network | ≥ 10 injury crashes in 5 years and no project in the period |", "|---|---|---|---|"]
        names = {"vision_zero_priority": "NYC Vision Zero priority intersections (random 10)",
                 "random_crash_location": "random 2025 crash locations (NYC 10, DC 10)", "demo": "demo junctions"}
        for gname, rows in groups.items():
            L.append(f"| {names.get(gname, gname)} | {len(rows)} | {sum(bool(r['designated']) for r in rows)} | "
                     f"{sum(bool(r['plan_gap']) for r in rows)} |")
        L += ["", "Descriptive only: \"project\" means a record in the city's open project datasets within 150 m; "
              "work outside those datasets is not seen. The first run's checker did not read numbers inside field names "
              "(the 400 in schools_400m, years used as keys), so it flagged 33 unchecked memos; the counts above use "
              "the fixed checker (post-hoc, disclosed)."]
        L.append("")
    sc = _load("scout_trial.json")
    if sc:
        L += ["## Scout trial (Muse Spark points → SAM 3.1 point prompts), development frames", "",
              "| kind | reference | SAM recall | SAM precision | SAM+Scout recall | SAM+Scout precision | go |", "|---|---|---|---|---|---|---|"]
        for k, r in sc.items():
            L.append(f"| {k} | {r['ref']} | {_f(r['sam_recall'])} | {_f(r['sam_precision'])} | {_f(r['scout_recall'])} | "
                     f"{_f(r['scout_precision'])} | {'yes' if r['go'] else 'no'} |")
        L.append("")
    arms = [(a, RESULTS_DIR / "test" / f"verifier{'' if a == 'full' else '_' + a}.json") for a in ("full", "no_video", "no_metric")]
    if all(p.exists() for _, p in arms):
        L += ["## Verifier ablation (test split, 175 candidate conflicts)", "", "| arm | judged real | precision | recall | F1 |", "|---|---|---|---|---|"]
        for a, pth in arms:
            v = json.loads(pth.read_text())
            L.append(f"| {a} | {v['judged_real']} | {_f(v['after']['precision'])} | {_f(v['after']['recall'])} | {_f(v['after']['f1'])} |")
        L.append("")
    rs = _load("fresh_reseed.json")
    if rs:
        L += ["## Re-seeding confirmation on the fresh windows (registered rule: PET ≤ 1.5 s F1 interval above 0)", "",
              "| pipeline | conflict set | matched | precision | recall | F1 | F2 |", "|---|---|---|---|---|---|---|"]
        for v, label in (("base", "v1 (Kalman/RTS)"), ("reseed", "v1 + re-seeding")):
            for k in ("ttc", "pet<=1.5", "pet<=3.0"):
                m = rs["pooled"][v][k]
                L.append(f"| {label} | {k} | {m['tp']} of {m['ref_events']} | {_f(m['precision'])} | {_f(m['recall'])} | "
                         f"{_f(m['f1'])} | {_f(m['f2'])} |")
        L += ["", f"PET ≤ 1.5 s F1 difference, 95% interval over flights: [{_f(rs['pet_f1_diff_ci95'][0])}, "
                  f"{_f(rs['pet_f1_diff_ci95'][1])}]: registered rule {'met' if rs['claim_reseed_better'] else 'not met'}. "
                  f"TTC F1 difference: [{_f(rs['ttc_f1_diff_ci95'][0])}, {_f(rs['ttc_f1_diff_ci95'][1])}].", ""]
    for name, title in (("citywide_nyc.json", "street projects plus LPI, turn calming and signal retiming (headline)"),
                        ("citywide_nyc_sip_only.json", "street projects only (first run)")):
        cw = _load(name)
        if cw:
            s_ = cw["summary"]
            L += [f"## T9 Citywide plan-gap screen, NYC Vision Zero priority intersections: {title}", "",
                  f"{s_['intersections']} intersections, {s_['injury_crashes_total']} injury crashes and {s_['killed_total']} "
                  f"deaths within 100 m in 5 years. Plan gap (≥ 10 injury crashes, no recorded treatment in the period): "
                  f"{s_['plan_gap']} ({_f(100 * s_['plan_gap_share'], 1)}%). No recorded treatment ever: {s_['never_a_project']}.", ""]
    fu = _load("fusion_dc.json")
    if fu:
        L += ["## T10 Near-miss and crash fusion, Washington DC (unseen 30% of 1 km blocks, future years)", "",
              "| target | model | top-5% precision | top-10% precision | Spearman |", "|---|---|---|---|---|"]
        for t, r in fu.items():
            for m, v in r["models"].items():
                L.append(f"| {t} | {m} | {_f(v['top5_precision'])} | {_f(v['top10_precision'])} | {_f(v['spearman'])} |")
        L += ["", "Fusion minus crash-history EB, top-5% precision: " + "; ".join(
            f"{t} [{_f(r['top5_diff_fusion_minus_crash_ci95'][0])}, {_f(r['top5_diff_fusion_minus_crash_ci95'][1])}]"
            for t, r in fu.items()) + ". Registered rule not met: residents' near-miss reports did not improve crash "
            "prediction over crash history, also at sites with little crash history (exploratory).", ""]
    from . import opendata
    auto = [a for a in opendata.load_registry() if a.get("provenance", {}).get("found_by") == "data agent"]
    if auto:
        L += ["## Data agent: adapters found and validated without hand-written code", "",
              "| place | dataset | validator attempts | records near the test point | latest record |", "|---|---|---|---|---|"]
        for a in auto:
            v = a["provenance"]["validation"]
            L.append(f"| {a['place']} | {a['source']} | {a['provenance'].get('attempts')} | {v.get('records_near')} | {v.get('latest')} |")
        L.append("")
    fv = _load("fresh_verify_open.json")
    if fv:
        b, a = fv["before"], fv["after"]
        L += ["## Open-weights verifier on the re-seeded fresh windows (registered)", "",
              "| set | candidates | matched | precision | recall | F1 |", "|---|---|---|---|---|---|",
              f"| all candidates | {b['pred_events']} | {b['tp']} of {b['ref_events']} | {_f(b['precision'])} | {_f(b['recall'])} | {_f(b['f1'])} |",
              f"| kept by Muse Spark Open (speed trace + metric) | {a['pred_events']} | {a['tp']} of {a['ref_events']} | "
              f"{_f(a['precision'])} | {_f(a['recall'])} | {_f(a['f1'])} |", "",
              f"F1 difference [{_f(fv['f1_diff_ci95'][0])}, {_f(fv['f1_diff_ci95'][1])}]: registered rule "
              f"{'met' if fv['claim_verifier_better'] else 'not met'}. Spark Open keeps too few candidates to help; "
              f"${fv['baseten_usd']} of Baseten credit.", ""]
    t20 = _load("top20_briefs.json") if (BENCH_DIR / "top20_briefs.json").exists() else None
    if t20:
        L += ["## Top-20 NYC plan-gap briefs", "",
              f"{len(t20)} briefs for the plan-gap intersections with the most injury crashes; checked memos written: "
              f"{sum(r['memo_ok'] for r in t20)}; fix drawings passing the SAM 3.1 check (junction area, real road users "
              f"protected): {sum(bool(r['illustration_check']) for r in t20)} of {len(t20)}.", ""]
    ow = _load("open_weights.json")
    if ow:
        L += ["## Open weights: Muse Spark Open (Baseten) as the conflict verifier", "",
              f"On {ow['answered']} of {ow['events']} candidate conflicts (test split), Muse Spark Open agreed with hosted Muse Spark "
              f"on {_f(100 * ow['agreement'], 1)}% of verdicts (Cohen's kappa {_f(ow['kappa'], 2)}), for ${_f(ow['open_usd_total'], 2)} of "
              "Baseten partner credit.", "", "| verifier | kept | precision | recall | F1 |", "|---|---|---|---|---|"]
        for n, k in (("hosted Muse Spark", "hosted_kept"), ("Muse Spark Open", "open_kept")):
            r = ow[k]
            L.append(f"| {n} | {r['pred_events']} | {_f(r['precision'])} | {_f(r['recall'])} | {_f(r['f1'])} |")
        L.append("")
    try:
        cj = cost_per_junction_hour()
        L += ["## Cost", "", f"SAM 3.1 tracking of the fresh windows: ${cj['sam_usd']} for {cj['minutes']:.0f} minutes of 4K video, "
              f"${cj['sam_usd_per_hour']} per hour.", ""]
    except Exception:
        pass
    text = "\n".join(L)
    (RESULTS_DIR.parent / "BENCH.md").write_text(text)
    return text


def _load(name: str) -> dict | None:
    p = BENCH_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def open_weights_agreement(split: str = "test") -> dict:
    """Muse Spark Open (Baseten) vs hosted Muse Spark on the same candidate conflicts: same clip, speed trace and
    metric. Reports agreement, Cohen's kappa, and both verifiers' precision/recall against the reference."""
    from . import openweights, runner, verifier
    from .baseline import score
    ev = pd.read_csv(RESULTS_DIR / split / "verifier_events.csv")
    c, ours = runner.site_states(split, "sam")
    st = ours.assign(id=ours["id"].astype(str))
    fps = pipeline.clip_fps(c)
    rows = []
    for e in ev.to_dict("records"):
        ids = (str(e["id_1"]), str(e["id_2"]))
        mid = int(round(e["t"] * fps))
        trace = verifier.speed_trace_png(st, ids[0], ids[1], mid, fps)
        metric = f"{e['measure']} {e['value']:.1f} s, {e['type'].replace('_', '-')}, A={e['cls_1']}, B={e['cls_2']}"
        try:
            o = openweights.verify_open(Path(e["clip"]), trace, metric, clip_key=f"{Path(e['clip']).name}|{metric}")
            v = (o["verdict"] or {}).get("real_conflict")
            usd = o["usd"]
        except Exception as err:
            v, usd = None, 0.0
            print(f"open verifier failed: {err}", flush=True)
        rows.append({**{k: e[k] for k in ("measure", "value", "type", "cls_1", "cls_2", "t", "x", "y", "id_1", "id_2")},
                     "hosted": bool(e["real_conflict"]), "open": v, "usd": usd})
    df = pd.DataFrame(rows)
    ok = df[df["open"].notna()]
    a, b = ok["hosted"].astype(bool), ok["open"].astype(bool)
    po = float((a == b).mean()) if len(ok) else float("nan")
    pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())) if len(ok) else float("nan")
    _, ref_states = runner.site_states(split, "reference")
    ref = audit.conflict_table(ref_states)
    cand = df[CONFLICT_KEYS]
    out = {"split": split, "events": len(df), "answered": len(ok), "agreement": po,
           "kappa": (po - pe) / (1 - pe) if pe == pe and pe < 1 else float("nan"),
           "open_usd_total": float(df["usd"].sum()),
           "hosted_kept": score(cand[df["hosted"]], ref), "open_kept": score(cand[df["open"] == True], ref)}  # noqa: E712
    _write("open_weights.json", out)
    return out


CONFLICT_KEYS = ["measure", "value", "type", "id_1", "id_2", "cls_1", "cls_2", "t", "x", "y"]


def rescore_complaint_numbers() -> dict:
    """Post-hoc, disclosed: re-check the numbers in stored T4 answers with the checker that reads decimal commas
    ('185,7'); the first run flagged such numbers as ungrounded. Structural errors are kept as recorded."""
    from . import ask, panel
    d = _load("complaints.json")
    gs = {a: panel.Grounding(*ask.load(a, SETTINGS.runs_dir)) for a in AUDITS}
    for r in d["rows"]:
        if r["method"] == "fixed_rule" or not r.get("errors"):
            r["errors_rescored"] = r.get("errors", [])
            continue
        structural = [e for e in r["errors"] if not e.startswith("number ")]
        r["errors_rescored"] = structural + gs[r["audit"]].text(r.get("answer") or "")
    df = pd.DataFrame(d["rows"])
    for m, g in df.groupby("method"):
        d["summary"][m]["ungrounded_answers_rescored"] = int((g["errors_rescored"].map(len) > 0).sum())
    _write("complaints.json", d)
    return {m: (s["ungrounded_answers"], s["ungrounded_answers_rescored"]) for m, s in d["summary"].items()}


def rescore_context_memos() -> dict:
    """Post-hoc, disclosed: re-check stored T8 memos with the fact checker that also reads numbers in field names
    (the 400 in schools_400m, the years in by_year). The first run counted those as ungrounded."""
    from . import context
    d = _load("context.json")
    for r in d["rows"]:
        dossier = context.dossier(r["lat"], r["lon"])  # served from the request cache
        chk = context.FactCheck(dossier)
        for arm in ("checked", "unchecked"):
            if arm in r:
                r[arm]["errors_rescored"] = chk.text(r[arm]["memo"] or "")
    for arm in ("checked", "unchecked"):
        d["summary"][arm]["memos_with_ungrounded_numbers_rescored"] = int(sum(bool(r[arm]["errors_rescored"]) for r in d["rows"]))
    _write("context.json", d)
    return {arm: (d["summary"][arm]["memos_with_ungrounded_numbers"], d["summary"][arm]["memos_with_ungrounded_numbers_rescored"])
            for arm in ("checked", "unchecked")}


def _bootstrap_diff(per: list[dict], key: str, a: str, b: str, n: int = 2000) -> list[float]:
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(n):
        idx = rng.integers(0, len(per), len(per))
        diffs.append(_pooled([per[i][b] for i in idx], key)["f1"] - _pooled([per[i][a] for i in idx], key)["f1"])
    return [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]


def fresh_reseed(client, flights=None) -> dict:
    """Registered re-seeding confirmation: the fresh windows tracked by the same code with and without re-seeding of
    "scooter", both scored with the chosen Kalman/RTS kinematics."""
    from . import evaluate, reseed, windows
    from .evaluate import CONCEPTS, chosen_kinematics
    kin = chosen_kinematics()
    per = []
    for site, stem in flights or windows.FRESH:
        wc = windows.window_clip(site, stem)
        cal = pipeline.calibration_for(wc)
        work = Path(SETTINGS.data_dir) / "work" / "fresh"
        frames = (windows.FRAME_OFFSET + 1, windows.FRAME_OFFSET + int(windows.DURATION_S * FLUID_FPS))
        row = {"site": site, "flight": stem}
        for name, flag in (("base", False), ("reseed", True)):
            pts, stats = reseed.track_with_reseed(client, wc, 0.0, windows.DURATION_S, CONCEPTS, work, cal, reseed=flag)
            pts = pts.assign(frame=pts["frame"] + windows.FRAME_OFFSET)
            pts["t"] = pts["frame"] / FLUID_FPS
            ours, ref, trk = evaluate.evaluate_tracks(pts, wc, frames, f"reseed {site} {stem} {name}", stitch=True,
                                                      kinematics=kin)
            s = evaluate.evaluate_conflicts(ours, ref, f"reseed {site} {stem} {name}")["summary"]
            row[name] = {"tracking": trk, "ttc": s["all"], "pet<=1.5": s["pet<=1.5"], "pet<=3.0": s["pet<=3.0"],
                         "stats": stats}
        per.append(row)
        print("scored", site, stem, flush=True)
    out = {"flights": per,
           "pooled": {v: {k: _pooled([r[v] for r in per], k) for k in ("ttc", "pet<=1.5", "pet<=3.0")} for v in ("base", "reseed")},
           "pet_f1_diff_ci95": _bootstrap_diff(per, "pet<=1.5", "base", "reseed"),
           "ttc_f1_diff_ci95": _bootstrap_diff(per, "ttc", "base", "reseed")}
    p = out["pooled"]
    out["claim_reseed_better"] = bool(p["reseed"]["pet<=1.5"]["f1"] > p["base"]["pet<=1.5"]["f1"] and out["pet_f1_diff_ci95"][0] > 0)
    _write("fresh_reseed.json", out)
    return out


def open_agent_arms(oc, arm: str = "spark_open_checked", t8_key: str = "open_checked", model: str = "muse-spark-open") -> dict:
    """Open-weights tier: the intake agent (T4 complaints) and the context memo agent (T8 junctions) on Muse Spark Open
    (Baseten), with the checker, next to the hosted runs already in complaints.json and context.json."""
    from . import ask, complaints, context
    from .countermeasures import load_cmf
    cmf = load_cmf()
    c4 = _load("complaints.json")
    c4["rows"] = [r for r in c4["rows"] if r["method"] != arm]
    for a in AUDITS:
        facts, memo_md = ask.load(a, SETTINGS.runs_dir)
        frames = Path(SETTINGS.data_dir) / "work" / "ask_frames"
        for k, c in enumerate(complaints.benchmark_set(facts)):
            exp_v, exp_r = ask.truth(c, facts)
            out = ask.answer(oc, c["text"], facts, memo_md, cmf, frames, f"t4{arm} {a} {k}", model=model,
                             budget_usd=0.3)
            r = out["result"] or {"verdict": "none", "rank": None, "errors": ["no answer"]}
            c4["rows"].append({"audit": a, "kind": c["kind"], "lang": c["lang"], "text": c["text"], "expected": exp_v,
                               "expected_ranks": sorted(exp_r), "method": arm, "verdict": r["verdict"],
                               "rank": r.get("rank"), "errors": r.get("errors", []), "errors_rescored": r.get("errors", []),
                               "usd": out["usd"], "turns": out["turns"], "stopped": out["stopped"],
                               "answer": r.get("answer"), **_score_complaint(r["verdict"], r.get("rank"), exp_v, exp_r)})
    g = pd.DataFrame([r for r in c4["rows"] if r["method"] == arm])
    c4["summary"][arm] = {
        "n": len(g), "accuracy": float(g["correct"].mean()), "verdict_accuracy": float(g["verdict_ok"].mean()),
        "ungrounded_answers": int((g["errors"].map(len) > 0).sum()),
        "ungrounded_answers_rescored": int((g["errors"].map(len) > 0).sum()),
        "usd_total": float(g["usd"].sum()), "usd_per_complaint": float(g["usd"].mean()),
        **{f"accuracy_{kind}": float(gk["correct"].mean()) for kind, gk in g.groupby("kind")}}
    _write("complaints.json", c4)
    c8 = _load("context.json")
    for row in c8["rows"]:
        d = context.dossier(row["lat"], row["lon"])
        m = context.memo(oc, d, f"t8{t8_key} {row['id']}")
        row[t8_key] = {"errors": m["errors"], "usd": m["usd"], "attempts": m["attempts"], "memo": m["memo"]}
    c8["summary"][t8_key] = {
        "memos_with_ungrounded_numbers": int(sum(bool(r[t8_key]["errors"]) for r in c8["rows"])),
        "usd_per_memo": float(np.mean([r[t8_key]["usd"] for r in c8["rows"]]))}
    _write("context.json", c8)
    return {"t4": c4["summary"][arm], "t8": c8["summary"][t8_key]}


def fresh_verify_open(windows_list=None, n_boot: int = 2000) -> dict:
    """Registered: Muse Spark Open (Baseten) judges every candidate conflict of the re-seeded fresh windows from the
    speed trace and metric (no video); scored before and after against the reference conflict table."""
    from . import evaluate, openweights, reseed, verifier, windows
    from .baseline import score
    from .meta_client import MetaClient
    from dataclasses import replace
    kin = evaluate.chosen_kinematics()
    client = MetaClient(replace(SETTINGS, replay=True))  # tracks are cached: this client can never make a paid call
    per = []
    for site, stem in windows_list or windows.FRESH:
        wc = windows.window_clip(site, stem)
        cal = pipeline.calibration_for(wc)
        pts, _ = reseed.track_with_reseed(client, wc, 0.0, windows.DURATION_S, evaluate.CONCEPTS,
                                          Path(SETTINGS.data_dir) / "work" / "fresh", cal, reseed=True)
        pts = pts.assign(frame=pts["frame"] + windows.FRAME_OFFSET)
        frames = (windows.FRAME_OFFSET + 1, windows.FRAME_OFFSET + int(windows.DURATION_S * FLUID_FPS))
        ours, ref, _ = evaluate.evaluate_tracks(pts, wc, frames, "verify open", stitch=True, kinematics=kin)
        cand = audit.conflict_table(ours)
        refc = audit.conflict_table(ref[ref["isReal"] == 1])
        st = ours.assign(id=ours["id"].astype(str))
        keep, usd = [], 0.0
        for e in cand.to_dict("records"):
            ids = (str(e["id_1"]), str(e["id_2"]))
            mid = int(round(e["t"] * FLUID_FPS))
            trace = verifier.speed_trace_png(st, ids[0], ids[1], mid, FLUID_FPS)
            metric = f"{e['measure']} {e['value']:.1f} s, {e['type'].replace('_', '-')}, A={e['cls_1']}, B={e['cls_2']}"
            o = openweights.verify_open(None, trace, metric, clip_key=f"fresh|{site}|{stem}|{ids[0]}|{ids[1]}|{mid}")
            usd += o.get("usd", 0.0)
            keep.append(bool((o.get("verdict") or {}).get("real_conflict", True)))
        kept = cand[keep] if len(cand) else cand
        per.append({"site": site, "flight": stem, "candidates": int(len(cand)), "kept": int(len(kept)),
                    "before": score(cand, refc), "after": score(kept, refc), "usd": round(usd, 4)})
        print("verified", site, stem, per[-1]["candidates"], "->", per[-1]["kept"], flush=True)

    def pooled(rows, key):
        tp = sum(r[key]["tp"] for r in rows)
        ref_n = sum(r[key]["ref_events"] for r in rows)
        pred = sum(r[key]["pred_events"] for r in rows)
        p = tp / pred if pred else float("nan")
        rc = tp / ref_n if ref_n else float("nan")
        return {"tp": tp, "ref_events": ref_n, "pred_events": pred, "precision": p, "recall": rc,
                "f1": 2 * p * rc / (p + rc) if pred and ref_n and (p + rc) else 0.0}

    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(per), len(per))
        rows = [per[i] for i in idx]
        diffs.append(pooled(rows, "after")["f1"] - pooled(rows, "before")["f1"])
    out = {"windows": per, "before": pooled(per, "before"), "after": pooled(per, "after"),
           "f1_diff_ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
           "baseten_usd": round(sum(r["usd"] for r in per), 3)}
    out["claim_verifier_better"] = bool(out["after"]["f1"] > out["before"]["f1"] and out["f1_diff_ci95"][0] > 0)
    _write("fresh_verify_open.json", out)
    return out
