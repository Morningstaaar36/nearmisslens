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
from .config import ROOT, portable
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
    (RESULTS_DIR / "bench" / f"experiment_{exp['id']}.json").write_text(portable(json.dumps(out, indent=1, default=float)))
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
            path.write_text(portable(json.dumps(done, indent=1, default=float)))
        c = res.get("claim") or {}
        print(f"{blind[key]} ({key}) {'gated' if gated else 'ungated'}: {c.get('claim')} {c.get('effect_pct')} "
              f"[{res['stopped']}, {res['turns']} turns, {res['code_runs']} code runs, ${res['usd']}]", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, jobs))
    return done


def run_agents_real(client, items: list[tuple[str, str]], name: str = "T12", model_label: str = "muse-spark-open",
                    workers: int = 3, executor: str = "local") -> dict:
    """The agentic arms on registered real programs in any city (study id, program key), blinded as P23, P24...;
    saved into the same results file as the New York arms."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from . import analyst
    exp = load(name)
    path = RESULTS_DIR / "bench" / f"experiment_{exp['id']}_agents_{model_label}.json"
    done = json.loads(path.read_text()) if path.exists() else {"id": exp["id"], "model": model_label, "runs": []}
    have = {(r["program_key"], r["gated"]) for r in done["runs"] if r.get("stopped") == "finish_tool"}
    lock = threading.Lock()
    jobs, cache = [], {}
    for j, (study, key) in enumerate(items):
        spec = T.load_spec(study)
        prog = next(p for p in spec["programs"] if p["key"] == key)
        city = spec["city"]
        if city not in cache:
            org = T.origin(city)
            cr = T.crashes(city, org)
            cache[city] = (org, cr, treatment_vertices(spec.get("exclude_near") or [prog["adapter"]], org))
        org, cr, avoid = cache[city]
        m0, m1 = int(cr["month"].min()), int(cr["month"].max())
        treated = prog["treated"] if prog["treated"] != "auto" else \
            [f"{T._label(m0 + spec['window_months'])}-01", f"{T._label(m1 - spec['window_months'])}-28"]
        pts = T.program_points(opendata.adapter(prog["adapter"]))
        for gated in (False, True):
            if (f"{study}:{key}", gated) not in have:
                jobs.append((f"P{23 + j:02d}", f"{study}:{key}", pts, cr, org, avoid, treated, gated,
                             {**exp, "outcome": prog["outcome"]}, spec))

    def one(job):
        pid, pkey, pts, cr, org, avoid, treated, gated, ex, spec = job
        try:
            res = analyst.analyse(client, pid, pts, cr, org, avoid, gated, ex, spec, treated,
                                  tag=f"T12 {model_label}", executor=executor)
        except Exception as e:  # recorded, not hidden; a later call retries it
            res = {"program": pid, "gated": gated, "claim": None, "stopped": f"error: {type(e).__name__}: {e}",
                   "turns": 0, "code_runs": 0, "usd": 0.0}
        res.update(program_key=pkey, fake=False)
        with lock:
            done["runs"].append(res)
            path.write_text(portable(json.dumps(done, indent=1, default=float)))
        c = res.get("claim") or {}
        print(f"{pid} ({pkey}) {'gated' if gated else 'ungated'}: {c.get('claim')} {c.get('effect_pct')} "
              f"[{res['stopped']}, {res['turns']} turns, ${res['usd']}]", flush=True)
    with ThreadPoolExecutor(workers) as ex_:
        list(ex_.map(one, jobs))
    return done


# ---------------------------------------------------------------- T14: the calibrated gate

def null_thetas(cr: pd.DataFrame, cells: np.ndarray, org, design: dict, n_sites: int, install_range: list[str],
                base: dict, m: int = 200, seed0: int = 50_000) -> np.ndarray:
    """theta for m fake programs run through the same design (point estimates only): the empirical null a real
    program must beat. Fake programs have as many sites as the program under test, up to 80% of the hotspot cells;
    for a larger program the spread of log theta is narrowed by sqrt(cells used / sites), as averages over more sites
    are."""
    size = min(n_sites, int(0.8 * len(cells)))
    comp = design["comparison"]
    spec = {"id": "null", "city": "null", "merge_m": base["merge_m"], "neighbour_m": base["neighbour_m"],
            "radius_m": int(design["radius_m"]), "window_months": int(design["window_months"]), "placebo": None,
            "n_boot": 0, "outcomes": [design["outcome"]], "exclude_near": ["prog"],
            "programs": [{"key": "prog", "adapter": "prog", "treated": install_range, "comparisons": [comp],
                          "primary": comp, "outcome": design["outcome"]}]}
    lo, hi = (T._month(d) for d in install_range)
    out = []
    for k in range(m):
        rng = np.random.default_rng(seed0 + k)
        pick = cells[rng.choice(len(cells), size=size, replace=False)]
        lat, lon = latlon(pick, org)
        pts = pd.DataFrame({"lat": lat, "lon": lon, "month": rng.integers(lo, hi + 1, size=size)})
        r = T.evaluate_suite(spec, cr, {"prog": pts}, org)["runs"][f"prog_{comp}"][design["outcome"]]
        if r and r.get("theta"):
            out.append(r["theta"])
    t = np.log(np.array(out))
    if n_sites > size:
        c = np.median(t)
        t = c + (t - c) * np.sqrt(size / n_sites)
    return np.exp(t)


def calibrated(verdict_reduced: bool, verdict_increased: bool, theta: float | None, null: np.ndarray) -> dict:
    """The calibrated verdict: the old gate's verdict, and theta beyond the 2.5th (or 97.5th) percentile of the null."""
    lo, hi = (float(np.percentile(null, q)) for q in (2.5, 97.5))
    red = bool(verdict_reduced and theta is not None and theta < lo)
    inc = bool(verdict_increased and theta is not None and theta > hi)
    return {"verdict": "reduced" if red else ("increased" if inc else "no_evidence"), "null_p2_5": round(lo, 3),
            "null_p97_5": round(hi, 3), "null_n": int(len(null)),
            "null_rank": round(float((null <= theta).mean()), 3) if theta is not None else None}


def run_t14a(name: str = "T12", seeds: range = range(1000, 1100), designs: dict | None = None, m: int = 200) -> dict:
    """T14 (a): false-pass rates of the old and calibrated gates on fresh fake programs under two designs."""
    exp = load(name)
    base = T.load_spec(exp["base_study"])
    org = T.origin(exp["city"])
    cr = T.crashes(exp["city"], org)
    cells = hotspot_cells(cr, exp["fake"], treatment_vertices(exp["fake"]["clear_of"], org))
    designs = designs or {"T11": {"radius_m": 50, "window_months": 36, "comparison": "not_yet_treated", "outcome": "pedestrian"},
                          "short": {"radius_m": 30, "window_months": 12, "comparison": "not_yet_treated", "outcome": "pedestrian"}}
    rng_range = exp["fake"]["install_range"]
    out = {"id": "T14a", "registered": "validation/BENCH_PREREG.md, T14", "designs": {}}
    for dname, design in designs.items():
        null = null_thetas(cr, cells, org, design, exp["fake"]["sites"], rng_range, base, m=m)
        w = int(design["window_months"])
        spec = {"id": "t14", "city": "t14", "merge_m": base["merge_m"], "neighbour_m": base["neighbour_m"],
                "radius_m": int(design["radius_m"]), "window_months": w,
                "placebo": {"shift_months": w // 2 + 1, "window_months": w // 2}, "outcomes": [design["outcome"]],
                "exclude_near": ["prog"],
                "programs": [{"key": "prog", "adapter": "prog", "treated": rng_range, "comparisons": [design["comparison"]],
                              "primary": design["comparison"], "outcome": design["outcome"],
                              "placebo_same_sites": [design["comparison"]]}]}
        rows = []
        for k in seeds:
            pts = fake_points(k, cells, exp["fake"], org)
            res = T.evaluate_suite(spec, cr, {"prog": pts}, org)
            g = res["gates"]["prog"]
            mm = res["runs"][g["primary"]][design["outcome"]] or {}
            inc = bool(mm.get("ci95") and mm["ci95"][0] > 1 and g["placebo_ok"])
            cal = calibrated(g["passed"], inc, mm.get("theta"), null)
            rows.append({"seed": k, "theta": mm.get("theta"), "ci95": mm.get("ci95"), "old": "reduced" if g["passed"] else
                         ("increased" if inc else "no_evidence"), "calibrated": cal["verdict"], "null_rank": cal["null_rank"]})
        n = len(rows)
        old_k = sum(r["old"] != "no_evidence" for r in rows)
        cal_k = sum(r["calibrated"] != "no_evidence" for r in rows)
        out["designs"][dname] = {"design": design, "null_p2_5": round(float(np.percentile(null, 2.5)), 3),
                                 "null_p97_5": round(float(np.percentile(null, 97.5)), 3), "null_n": int(len(null)),
                                 "old_false_passes": old_k, "calibrated_false_passes": cal_k, "programs": n,
                                 "old_wilson95": wilson(old_k, n), "calibrated_wilson95": wilson(cal_k, n), "rows": rows}
        print(dname, "old", old_k, "calibrated", cal_k, "of", n, flush=True)
    (RESULTS_DIR / "bench" / "experiment_T14a.json").write_text(portable(json.dumps(out, indent=1, default=float)))
    return out


def run_t14b(name: str = "T12", m: int = 200) -> dict:
    """T14 (b): power. The calibrated gate on New York's and Seattle's LPIs under T11's design, all sites and the
    held-out half (split seed of the T12 agentic arms)."""
    from . import analyst
    exp = load(name)
    design = {"radius_m": 50, "window_months": 36, "comparison": "not_yet_treated", "outcome": "pedestrian"}
    out = {"id": "T14b", "registered": "validation/BENCH_PREREG.md, T14", "programs": []}
    for study, key in (("T11", "lpi"), ("T13_seattle", "lpi")):
        spec = T.load_spec(study)
        prog = next(p for p in spec["programs"] if p["key"] == key)
        city = spec["city"]
        org = T.origin(city)
        cr = T.crashes(city, org)
        clear = [a["id"] for a in opendata.adapters_of(city, "project")]
        cells = hotspot_cells(cr, exp["fake"], treatment_vertices(clear, org))
        m0, m1 = int(cr["month"].min()), int(cr["month"].max())
        treated = prog["treated"] if prog["treated"] != "auto" else \
            [f"{T._label(m0 + 36)}-01", f"{T._label(m1 - 36)}-28"]
        pts = T.program_points(opendata.adapter(prog["adapter"]))
        site_df = T.sites(pts, spec["merge_m"], org).reset_index(drop=True)
        half = analyst.split(len(site_df), exp["agentic"]["split_seed"])
        for part, subset in (("all sites", site_df), ("held-out half", site_df[~half])):
            g = analyst.gate_verdict(cr, subset[["lat", "lon", "month"]], org, design, treated, spec)
            theta = None if g["effect_pct"] is None else 1 + g["effect_pct"] / 100
            null = null_thetas(cr, cells, org, design, int(g["sites"] or 0), treated, spec, m=m)
            cal = calibrated(g["verdict"] == "reduced", g["verdict"] == "increased", theta, null)
            out["programs"].append({"study": study, "program": key, "part": part, "sites": g["sites"],
                                    "effect_pct": g["effect_pct"], "interval_pct": g["interval_pct"],
                                    "old": g["verdict"], "calibrated": cal["verdict"], "cells": int(len(cells)), **cal})
            print(study, part, g["sites"], g["effect_pct"], g["interval_pct"], "old", g["verdict"], "calibrated",
                  cal["verdict"], "null 2.5%", cal["null_p2_5"], "rank", cal["null_rank"], "cells", len(cells), flush=True)
    (RESULTS_DIR / "bench" / "experiment_T14b.json").write_text(portable(json.dumps(out, indent=1, default=float)))
    return out


def run_t14c(name: str = "T12", m: int = 200) -> dict:
    """T14 (c): the gated analyst arm with the calibrated gate. The analyst's committed design and the gate's held-out
    estimate are already stored; only the verdict changes (the finish tool forces the claim to match it)."""
    exp = load(name)
    base = T.load_spec(exp["base_study"])
    org = T.origin(exp["city"])
    cr = T.crashes(exp["city"], org)
    cells = hotspot_cells(cr, exp["fake"], treatment_vertices(exp["fake"]["clear_of"], org))
    runs = json.loads((RESULTS_DIR / "bench" / f"experiment_{exp['id']}_agents_muse-spark-open.json").read_text())["runs"]
    out = {"id": "T14c", "registered": "validation/BENCH_PREREG.md, T14", "runs": []}
    for r in runs:
        g = r.get("gate")
        if not r["gated"] or not g or g.get("effect_pct") is None:
            continue
        treated = exp["fake"]["install_range"] if r["fake"] else \
            next(p for p in base["programs"] if p["key"] == r["program_key"])["treated"]
        null = null_thetas(cr, cells, org, g["design"], int(g["sites"]), treated, base, m=m)
        cal = calibrated(g["verdict"] == "reduced", g["verdict"] == "increased", 1 + g["effect_pct"] / 100, null)
        out["runs"].append({"program_key": r["program_key"], "fake": r["fake"], "design": g["design"], "sites": g["sites"],
                            "effect_pct": g["effect_pct"], "old": g["verdict"], **cal})
        print(r["program_key"], g["design"], g["effect_pct"], "old", g["verdict"], "calibrated", cal["verdict"],
              "rank", cal["null_rank"], flush=True)
    fk = [x for x in out["runs"] if x["fake"]]
    out["summary"] = {"fake_programs": len(fk), "old_false": sum(x["old"] != "no_evidence" for x in fk),
                      "calibrated_false": sum(x["verdict"] != "no_evidence" for x in fk)}
    (RESULTS_DIR / "bench" / "experiment_T14c.json").write_text(portable(json.dumps(out, indent=1, default=float)))
    return out


def rank_studies(m: int = 200, min_cells: int = 200, name: str = "T12") -> list[dict]:
    """Where each studied program's effect falls among m fake programs run through its registered design (T14's
    null), saved into its study result as gates[key]["fake_rank"]. Cities with fewer than min_cells hotspot cells get
    no rank: too few places to build a fair null."""
    exp = load(name)
    done = []
    for path in sorted((RESULTS_DIR / "bench").glob("study_*.json")):
        res = json.loads(path.read_text())
        sp, city = res["spec"], res["city"]
        org = T.origin(city)
        cr = T.crashes(city, org)
        clear = [a["id"] for a in opendata.adapters_of(city, "project")]
        cells = hotspot_cells(cr, exp["fake"], treatment_vertices(clear, org))
        m0, m1 = int(cr["month"].min()), int(cr["month"].max())
        for key, g in res["gates"].items():
            main = (res["runs"].get(g["primary"]) or {}).get(g["outcome"]) or {}
            if len(cells) < min_cells or not main.get("theta"):
                g["fake_rank"] = {"rank": None, "cells": int(len(cells)), "note": "too few hotspot cells for a null"}
            else:
                prog = next(p for p in sp["programs"] if p["key"] == key)
                treated = prog["treated"] if prog["treated"] != "auto" else \
                    [f"{T._label(m0 + sp['window_months'])}-01", f"{T._label(m1 - sp['window_months'])}-28"]
                design = {"radius_m": sp["radius_m"], "window_months": sp["window_months"],
                          "comparison": g["primary"][len(key) + 1:], "outcome": g["outcome"]}
                null = null_thetas(cr, cells, org, design, int(main["sites"]), treated, sp, m=m)
                g["fake_rank"] = {"rank": round(float((null <= main["theta"]).mean()), 3), "null_n": int(len(null)),
                                  "null_p2_5": round(float(np.percentile(null, 2.5)), 3), "cells": int(len(cells))}
            done.append({"study": res["id"], "program": key, **g["fake_rank"]})
            print(res["id"], key, g["fake_rank"], flush=True)
        path.write_text(portable(json.dumps(res, indent=1, default=float)))
    return done
