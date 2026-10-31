"""Falsification gates (NML-Bench T12, registered in validation/BENCH_PREREG.md): does the causal gate stop claims of
effects that do not exist, and still confirm one that does?

Fake programs are drawn from a city's injury-crash hotspots far from any recorded treatment and given random install
months: nothing was installed on those dates, so any effect an analysis finds is false. Three fixed analyses run on
every fake program and on the real programs of the base study:
    naive        after / before at the sites, what a quick analysis or a dashboard does;
    comparison   the base study's comparison-group design (sites treated later), without the placebo;
    gate         the full causal gate: the comparison-group design and every placebo.
The agentic arms (analyst.py) put an AI analyst in front of the same programs, with and without the gate. The
experiment's parameters are in validation/experiments/<id>.json."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import opendata
from . import treatments as T
from .config import ROOT
from .evaluate import RESULTS_DIR

EXPERIMENTS = ROOT / "validation" / "experiments"


def load(name: str) -> dict:
    return json.loads((EXPERIMENTS / f"{name}.json").read_text())


def latlon(p: np.ndarray, org: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of treatments.xy."""
    return org[0] + p[:, 1] / 110_574, org[1] + p[:, 0] / (111_320 * np.cos(np.radians(org[0])))


def _coords(g):
    """Every [lon, lat] pair inside a GeoJSON coordinates value or an ArcGIS geometry."""
    if isinstance(g, dict):
        if "x" in g:
            yield [g["x"], g["y"]]
        for k in ("coordinates", "paths", "rings", "points"):
            if k in g:
                yield from _coords(g[k])
    elif isinstance(g, list):
        if len(g) >= 2 and all(isinstance(v, (int, float)) for v in g[:2]):
            yield g[:2]
        else:
            for v in g:
                yield from _coords(v)


def treatment_vertices(ids: list[str], org: tuple[float, float]) -> np.ndarray:
    """Every vertex of every record of the given project adapters (points, and lines along their length)."""
    pts = []
    for aid in ids:
        a = opendata.adapter(aid)
        for r in opendata.rows_all(a):
            g = r.get(a.get("geo_field", "")) if a.get("geo_field") else r.get("_geometry")
            got = list(_coords(g)) if g else []
            if not got and r.get("_lat") is not None:
                got = [[r["_lon"], r["_lat"]]]
            pts += got
    arr = np.array(pts, float) if pts else np.zeros((0, 2))
    return T.xy(arr[:, 1], arr[:, 0], org) if len(arr) else np.zeros((0, 2))


def hotspot_cells(cr: pd.DataFrame, fake: dict, clear_xy: np.ndarray) -> np.ndarray:
    """Centres (crash-weighted, metres) of grid cells with at least min_injury_crashes injury crashes over the record,
    more than clear_of_m from any recorded treatment."""
    inj = cr[cr["injury"]]
    cell = np.floor(inj[["x", "y"]].to_numpy() / fake["cell_m"]).astype(np.int64)
    key = cell[:, 0] * 1_000_003 + cell[:, 1]
    df = pd.DataFrame({"k": key, "x": inj["x"].to_numpy(), "y": inj["y"].to_numpy()})
    g = df.groupby("k").agg(n=("x", "size"), x=("x", "mean"), y=("y", "mean"))
    g = g[g["n"] >= fake["min_injury_crashes"]]
    centres = g[["x", "y"]].to_numpy()
    if len(clear_xy):
        d, _ = cKDTree(clear_xy).query(centres, distance_upper_bound=fake["clear_of_m"])
        centres = centres[np.isinf(d)]
    return centres


def fake_points(k: int, cells: np.ndarray, fake: dict, org: tuple[float, float]) -> pd.DataFrame:
    """Fake program k: `sites` hotspot cells and a random install month for each (seed k)."""
    rng = np.random.default_rng(k)
    pick = cells[rng.choice(len(cells), size=min(fake["sites"], len(cells)), replace=False)]
    lo, hi = (T._month(d) for d in fake["install_range"])
    lat, lon = latlon(pick, org)
    return pd.DataFrame({"lat": lat, "lon": lon, "month": rng.integers(lo, hi + 1, size=len(pick))})


def naive(cr: pd.DataFrame, points: pd.DataFrame, org, radius_m: float, window: int, outcome: str,
          treated: list[str], n_boot: int = T.N_BOOT, seed: int = T.SEED) -> dict:
    """After / before at the sites, no comparison group; a bootstrap interval over sites."""
    s = T.sites(points, 30, org)
    m0, m1 = int(cr["month"].min()), int(cr["month"].max())
    lo, hi = (T._month(d) for d in treated)
    m = s["month"].to_numpy()
    keep = (m >= lo) & (m <= hi) & (m - window >= m0) & (m + window <= m1)
    s = s[keep].reset_index(drop=True)
    mat = T.monthly_counts(s, cr, m0, m1, radius_m)[outcome]
    before = T._window_sum(mat, s["month"].to_numpy() - window - m0, window)
    after = T._window_sum(mat, s["month"].to_numpy() + 1 - m0, window)
    theta = after.sum() / max(before.sum(), 1)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        w = rng.multinomial(len(s), np.full(len(s), 1 / len(s)))
        boots.append((w * after).sum() / max((w * before).sum(), 1))
    lo_, hi_ = np.percentile(boots, [2.5, 97.5])
    return {"theta": round(float(theta), 3), "ci95": [round(float(lo_), 3), round(float(hi_), 3)],
            "sites": int(len(s)), "after": int(after.sum()), "before": int(before.sum())}


def gate_spec(exp: dict, base: dict, key: str, adapter_id: str, comparison: str = "not_yet_treated",
              treated: list[str] | None = None) -> dict:
    """The base study's design for one program, restricted to the experiment's outcome."""
    return {**{k: base[k] for k in ("merge_m", "neighbour_m", "placebo")}, "id": f"{exp['id']}_{key}",
            "city": exp["city"], "radius_m": exp["radius_m"], "window_months": exp["window_months"],
            "outcomes": [exp["outcome"]], "exclude_near": [adapter_id],
            "programs": [{"key": key, "adapter": adapter_id, "treated": treated or exp["fake"]["install_range"],
                          "comparisons": [comparison], "primary": comparison, "outcome": exp["outcome"],
                          "placebo_same_sites": [comparison]}]}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def claims(r: dict) -> str:
    """What an arm claims from an estimate: a reduction if the interval is entirely below 1."""
    ci = r.get("ci95") if r else None
    if not ci:
        return "no evidence"
    return "reduced" if ci[1] < 1 else ("increased" if ci[0] > 1 else "no evidence")


def run(name: str = "T12", programs: int | None = None) -> dict:
    exp = load(name)
    base = T.load_spec(exp["base_study"])
    org = T.origin(exp["city"])
    cr = T.crashes(exp["city"], org)
    cells = hotspot_cells(cr, exp["fake"], treatment_vertices(exp["fake"]["clear_of"], org))
    o = exp["outcome"]
    rows = []
    for k in range(programs or exp["fake"]["programs"]):
        pts = fake_points(k, cells, exp["fake"], org)
        nv = naive(cr, pts, org, exp["radius_m"], exp["window_months"], o, exp["fake"]["install_range"])
        suite = T.evaluate_suite(gate_spec(exp, base, "fake", "fake"), cr, {"fake": pts}, org)
        cg = suite["runs"]["fake_not_yet_treated"][o]
        rows.append({"program": k, "naive": nv, "comparison": cg, "gate": suite["gates"]["fake"],
                     "claims": {"naive": claims(nv), "comparison": claims(cg),
                                "gate": "reduced" if suite["gates"]["fake"]["passed"] else "no evidence"}})
        if k % 20 == 0:
            print(f"fake program {k}: naive {nv['theta']} {claims(nv)}, comparison {cg and cg['theta']}, "
                  f"gate {'passed' if suite['gates']['fake']['passed'] else 'no'}", flush=True)
    real = []
    base_res = json.loads((RESULTS_DIR / "bench" / f"study_{exp['base_study']}.json").read_text())
    for p in base["programs"]:
        if p["key"] not in exp["real"]:
            continue
        pts = T.program_points(opendata.adapter(p["adapter"]))
        nv = naive(cr, pts, org, exp["radius_m"], exp["window_months"], o, p["treated"])
        g = base_res["gates"][p["key"]]
        real.append({"program": p["key"], "label": p.get("label"), "naive": nv,
                     "primary": base_res["runs"][g["primary"]][g["outcome"]], "gate": g,
                     "claims": {"naive": claims(nv), "comparison": claims(base_res["runs"][g["primary"]][g["outcome"]]),
                                "gate": "reduced" if g["passed"] else "no evidence"}})
    summary = {}
    for arm in ("naive", "comparison", "gate"):
        k = sum(r["claims"][arm] == "reduced" for r in rows)
        eff = [r[arm]["theta"] for r in rows if arm != "gate" and r[arm] and r[arm].get("theta") is not None]
        summary[arm] = {"false_claims": k, "programs": len(rows), "rate": round(k / max(len(rows), 1), 3),
                        "wilson95": wilson(k, len(rows)),
                        "mean_theta": round(float(np.mean(eff)), 3) if eff else None}
    out = {"id": exp["id"], "registered": exp["registered"], "experiment": exp, "cells": int(len(cells)),
           "summary": summary, "fake": rows, "real": real,
           "rule_met_part_c": bool(summary["gate"]["rate"] < summary["naive"]["rate"]
                                   and summary["gate"]["wilson95"][1] <= 0.10)}
    (RESULTS_DIR / "bench" / f"experiment_{exp['id']}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def run_agents(client, name: str = "T12", model_label: str = "muse-spark-open", only: list[str] | None = None,
               arms: tuple[bool, ...] = (False, True), workers: int = 4, executor: str = "modal") -> dict:
    """The agentic arms: the first fake programs and the real ones, blinded, each analysed ungated and gated. Results
    are saved after every run (experiment_<id>_agents_<model>.json), and a finished run is not repeated."""
    from . import analyst
    exp = load(name)
    base = T.load_spec(exp["base_study"])
    org = T.origin(exp["city"])
    cr = T.crashes(exp["city"], org)
    avoid = treatment_vertices(exp["fake"]["clear_of"], org)
    cells = hotspot_cells(cr, exp["fake"], avoid)
    progs = [(f"fake_{k}", fake_points(k, cells, exp["fake"], org), exp["fake"]["install_range"])
             for k in range(exp["agentic"]["fake_programs"])]
    for p in base["programs"]:
        if p["key"] in exp["real"]:
            progs.append((p["key"], T.program_points(opendata.adapter(p["adapter"])), p["treated"]))
    order = np.random.default_rng(exp["agentic"]["split_seed"]).permutation(len(progs))
    blind = {progs[i][0]: f"P{j + 1:02d}" for j, i in enumerate(order)}
    import threading
    from concurrent.futures import ThreadPoolExecutor
    path = RESULTS_DIR / "bench" / f"experiment_{exp['id']}_agents_{model_label}.json"
    done = json.loads(path.read_text()) if path.exists() else {"id": exp["id"], "model": model_label, "runs": []}
    have = {(r["program_key"], r["gated"]) for r in done["runs"]
            if r.get("stopped") == "finish_tool" and r.get("executor", "modal") == executor}
    done["runs"] = [r for r in done["runs"] if (r["program_key"], r["gated"]) in have]
    lock = threading.Lock()
    jobs = [(key, pts, treated, gated) for key, pts, treated in progs if not only or key in only
            for gated in arms if (key, gated) not in have]

    def one(job):
        key, pts, treated, gated = job
        try:
            res = analyst.analyse(client, blind[key], pts, cr, org, avoid, gated, exp, base, treated,
                                  tag=f"T12 {model_label}", executor=executor)
        except Exception as e:  # recorded, not hidden; a later call retries it
            res = {"program": blind[key], "gated": gated, "claim": None, "stopped": f"error: {type(e).__name__}: {e}",
                   "turns": 0, "code_runs": 0, "usd": 0.0}
        res.update(program_key=key, fake=key.startswith("fake_"))
        with lock:
            done["runs"].append(res)
            path.write_text(json.dumps(done, indent=1, default=float))
        c = res.get("claim") or {}
        print(f"{blind[key]} ({key}) {'gated' if gated else 'ungated'}: {c.get('claim')} {c.get('effect_pct')} "
              f"[{res['stopped']}, {res['turns']} turns, {res['code_runs']} code runs, ${res['usd']}]", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, jobs))
    return done
