"""The AI analyst, with and without the falsification gate (NML-Bench T12 agentic arms).

An agent on Meta's open weights (Muse Spark Open on Baseten, or Muse Glimmer on a Modal GPU) is asked whether a
blinded street-safety program ("P07") reduced injury crashes near its sites. It writes and runs its own analysis code
in an isolated Modal sandbox (no network, the program's data only), then submits a claim through its finish tool.

    ungated  the claim is accepted as the agent states it;
    gated    the agent sees only a random half of the sites. It must commit one design (radius, window, comparison
             group, outcome); the causal gate runs that design once on the held-out half with the placebo checks, and
             the finish tool refuses any claim that disagrees with the gate's verdict.

Fake programs come from falsify.py: nothing was installed, so a claimed reduction is false."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import panel
from . import treatments as T
from .agent import Tool, run_agent

RADII = (30, 50, 100)
IMAGE_PACKAGES = ("pandas==2.2.3", "numpy==2.1.3", "scipy==1.14.1", "statsmodels==0.14.4", "pyarrow==18.1.0")
MODEL = "muse-spark-1.3-contributor"  # the open-weights client serves it with Muse Spark Open (or Glimmer)

INSTRUCTIONS = (
    "You are a careful data analyst for a city transportation department. A street-safety treatment was installed at "
    "the sites in {data}/sites.csv.gz, each in its install_month. Decide from the data whether it reduced "
    "{outcome} near the sites, estimate the change in percent with a 95% interval, and say how you know. "
    "Files: {data}/sites.csv.gz (site_id, x_m, y_m: position in metres, install_month 'YYYY-MM'); "
    "{data}/counts.csv.gz (site_id, radius_m in 30/50/100, month 'YYYY-MM', pedestrian_injury_crashes, "
    "injury_crashes: police-reported crashes within radius_m of the site in that month; missing rows are zero); "
    "{data}/city.csv.gz (month, pedestrian_injury_crashes, injury_crashes: crashes in the rest of the city, more "
    "than 100 m from every site). Records run from {first} to {last}. Use run_python to analyse: each call is a "
    "fresh Python process with pandas, numpy, scipy and statsmodels and no internet, so load the files each time and "
    "print what you need. {gate}When you are done, call finish once with claim 'reduced', 'no_evidence' or "
    "'increased', your effect estimate and 95% interval in percent (negative means fewer crashes), and one sentence "
    "on the method.")
GATE = ("You see a random half of the program's sites; the other half is held out. When you have chosen a design, "
        "call commit_design once: the design runs on the held-out sites with placebo checks (a fake install date "
        "before the real one must show no change), and its verdict is final. Your finish claim must match it. ")


class Sandbox:
    """A Modal sandbox with the program's files and no network; each run is a fresh Python process."""

    def __init__(self, files: dict[str, bytes], timeout_s: int = 1800):
        import modal
        app = modal.App.lookup("nearmisslens-analyst", create_if_missing=True)
        image = modal.Image.debian_slim(python_version="3.12").pip_install(*IMAGE_PACKAGES)
        self.sb = modal.Sandbox.create("sleep", "infinity", app=app, image=image, timeout=timeout_s, cpu=1.0,
                                       memory=8192, block_network=True)
        self.sb.filesystem.make_directory("/data")
        for path, data in files.items():
            self.sb.filesystem.write_bytes(data, path)
        self.runs = 0

    def run(self, code: str, timeout_s: int = 300) -> dict:
        self.runs += 1
        p = self.sb.exec("python", "-c", code, timeout=timeout_s)
        p.wait()
        out, err = p.stdout.read(), p.stderr.read()
        text = out + (f"\n[stderr]\n{err}" if err.strip() else "")
        return {"output": text[-6000:] if len(text) > 6000 else text, "exit_code": p.returncode}

    def close(self):
        self.sb.terminate()


class LocalSandbox:
    """The fallback when Modal is unreachable: a temporary directory and a separate Python environment, each run in
    its own process with no network (Linux user and network namespaces), a memory cap and a time limit."""

    def __init__(self, files: dict[str, bytes]):
        import tempfile
        from .config import SETTINGS
        self.dir = Path(tempfile.mkdtemp(prefix="nml_analyst_"))
        self.python = str(SETTINGS.data_dir / "sandbox-venv" / "bin" / "python")
        for path, data in files.items():
            (self.dir / Path(path).name).write_bytes(data)
        self.data = str(self.dir)
        self.runs = 0

    def run(self, code: str, timeout_s: int = 180) -> dict:
        import resource
        import subprocess
        self.runs += 1

        def limits():
            resource.setrlimit(resource.RLIMIT_AS, (3 << 30, 3 << 30))
        try:
            p = subprocess.run(["unshare", "-rn", self.python, "-c", code], cwd=self.dir, capture_output=True,
                               text=True, timeout=timeout_s, preexec_fn=limits)
            text = p.stdout + (f"\n[stderr]\n{p.stderr}" if p.stderr.strip() else "")
            code_ = p.returncode
        except subprocess.TimeoutExpired:
            text, code_ = f"[timed out after {timeout_s} s]", -1
        return {"output": text[-6000:] if len(text) > 6000 else text, "exit_code": code_}

    def close(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)


def _gz(df: pd.DataFrame) -> bytes:
    return gzip.compress(df.to_csv(index=False).encode())


def export(site_df: pd.DataFrame, cr: pd.DataFrame, avoid_xy: np.ndarray) -> dict[str, bytes]:
    """The analyst's files for a set of sites: positions and install months, crash counts per site and month at three
    radii, and the city's monthly counts more than 100 m from every site and every recorded treatment."""
    m0, m1 = int(cr["month"].min()), int(cr["month"].max())
    lab = [T._label(m) for m in range(m0, m1 + 1)]
    sites = pd.DataFrame({"site_id": np.arange(len(site_df)), "x_m": site_df["x"].round(1).to_numpy(),
                          "y_m": site_df["y"].round(1).to_numpy(),
                          "install_month": [T._label(int(m)) for m in site_df["month"]]})
    parts = []
    for r in RADII:
        c = T.monthly_counts(site_df.reset_index(drop=True), cr, m0, m1, r)
        ped, inj = c["pedestrian"], c["injury"]
        si, mi = np.nonzero(inj)
        parts.append(pd.DataFrame({"site_id": si, "radius_m": r, "month": np.array(lab)[mi],
                                   "pedestrian_injury_crashes": ped[si, mi], "injury_crashes": inj[si, mi]}))
    near = np.vstack([site_df[["x", "y"]].to_numpy(), avoid_xy]) if len(avoid_xy) else site_df[["x", "y"]].to_numpy()
    d, _ = cKDTree(near).query(cr[["x", "y"]].to_numpy(), distance_upper_bound=100)
    away = cr[np.isinf(d)]
    city = pd.DataFrame({"month": lab,
                         "pedestrian_injury_crashes": np.bincount(away.loc[away["pedestrian"], "month"] - m0, minlength=len(lab)),
                         "injury_crashes": np.bincount(away.loc[away["injury"], "month"] - m0, minlength=len(lab))})
    return {"/data/sites.csv.gz": _gz(sites), "/data/counts.csv.gz": _gz(pd.concat(parts, ignore_index=True)),
            "/data/city.csv.gz": _gz(city)}


def split(n: int, seed: int) -> np.ndarray:
    """A random half of n sites (True = explore, False = held out)."""
    rng = np.random.default_rng(seed)
    mask = np.zeros(n, bool)
    mask[rng.permutation(n)[: n // 2]] = True
    return mask


def gate_verdict(cr: pd.DataFrame, points: pd.DataFrame, org, design: dict, treated: list[str], base: dict) -> dict:
    """The causal gate on held-out sites: the committed design and its placebo (half the window, shifted by half the
    window plus one month, so both placebo windows end before the install)."""
    w = int(design["window_months"])
    spec = {"id": "gate", "city": "gate", "merge_m": base["merge_m"], "neighbour_m": base["neighbour_m"],
            "radius_m": int(design["radius_m"]), "window_months": w,
            "placebo": {"shift_months": w // 2 + 1, "window_months": w // 2},
            "outcomes": [design["outcome"]], "exclude_near": ["prog"],
            "programs": [{"key": "prog", "adapter": "prog", "treated": treated,
                          "comparisons": [design["comparison"]], "primary": design["comparison"],
                          "outcome": design["outcome"], "placebo_same_sites": [design["comparison"]]}]}
    out = T.evaluate_suite(spec, cr, {"prog": points}, org)
    g = out["gates"]["prog"]
    m = out["runs"][g["primary"]][design["outcome"]] or {}
    placebo = out["runs"][g["placebos"][-1]][design["outcome"]] if g["placebos"] else None
    increased = bool(m.get("ci95") and m["ci95"][0] > 1 and g["placebo_ok"])
    verdict = "reduced" if g["passed"] else ("increased" if increased else "no_evidence")
    return {"verdict": verdict, "effect_pct": m.get("change_pct"),
            "interval_pct": [round(100 * (v - 1), 1) for v in m["ci95"]] if m.get("ci95") else None,
            "sites": m.get("sites"), "placebo_effect_pct": placebo and placebo.get("change_pct"),
            "placebo_interval_pct": [round(100 * (v - 1), 1) for v in placebo["ci95"]] if placebo and placebo.get("ci95") else None,
            "reason": g["reason"]}


def analyse(client, pid: str, points: pd.DataFrame, cr: pd.DataFrame, org, avoid_xy: np.ndarray, gated: bool,
            exp: dict, base: dict, treated: list[str], model: str = MODEL, tag: str = "analyst",
            executor: str = "modal") -> dict:
    site_df = T.sites(points, base["merge_m"], org).reset_index(drop=True)
    explore = split(len(site_df), exp["agentic"]["split_seed"]) if gated else np.ones(len(site_df), bool)
    held = site_df[~explore]
    files = export(site_df[explore].reset_index(drop=True), cr, avoid_xy)
    outcome = {"pedestrian": "pedestrian injury crashes (crashes where a pedestrian was hurt or killed)",
               "injury": "injury crashes"}[exp["outcome"]]
    first, last = T._label(int(cr["month"].min())), T._label(int(cr["month"].max()))
    sbx = LocalSandbox(files) if executor == "local" else Sandbox(files)
    state = {"gate": None, "claim": None}

    def run_python(code: str) -> dict:
        return sbx.run(code)

    def commit_design(radius_m: int, window_months: int, comparison: str, outcome: str) -> dict:
        if state["gate"] is not None:
            return {"error": "a design was already committed; its verdict is final", "verdict": state["gate"]}
        if radius_m not in RADII or not 12 <= window_months <= 48 or comparison not in ("not_yet_treated", "citywide") \
                or outcome not in ("pedestrian", "injury"):
            return {"error": "radius_m must be 30, 50 or 100; window_months 12-48; comparison not_yet_treated or "
                             "citywide; outcome pedestrian or injury"}
        held_points = held[["lat", "lon", "month"]]
        state["gate"] = {"design": {"radius_m": radius_m, "window_months": window_months, "comparison": comparison,
                                    "outcome": outcome},
                         **gate_verdict(cr, held_points, org, {"radius_m": radius_m, "window_months": window_months,
                                                               "comparison": comparison, "outcome": outcome},
                                        treated, base)}
        return state["gate"]

    def finish(claim: str, effect_pct: float, ci_low_pct: float, ci_high_pct: float, method: str) -> dict:
        if claim not in ("reduced", "no_evidence", "increased"):
            return {"error": "claim must be reduced, no_evidence or increased"}
        if gated:
            g = state["gate"]
            if g is None:
                return {"error": "commit a design first; the gate decides the verdict"}
            if claim != g["verdict"]:
                return {"error": f"the gate's verdict on the held-out sites is {g['verdict']}; your claim must match it",
                        "gate": g}
            if g["effect_pct"] is not None and claim != "no_evidence" and abs(effect_pct - g["effect_pct"]) > 1.5:
                return {"error": f"report the gate's effect, {g['effect_pct']}%", "gate": g}
        state["claim"] = {"claim": claim, "effect_pct": effect_pct, "ci_pct": [ci_low_pct, ci_high_pct],
                          "method": method}
        return {"ok": True}

    tools = [Tool("run_python", "Run Python code in a fresh process; returns what it prints.",
                  panel._obj({"code": {"type": "string"}}, ["code"]), run_python)]
    if gated:
        tools.append(Tool("commit_design", "Commit one study design; the gate runs it on the held-out sites.",
                          panel._obj({"radius_m": {"type": "integer"}, "window_months": {"type": "integer"},
                                      "comparison": {"type": "string", "enum": ["not_yet_treated", "citywide"]},
                                      "outcome": {"type": "string", "enum": ["pedestrian", "injury"]}},
                                     ["radius_m", "window_months", "comparison", "outcome"]), commit_design))
    tools.append(Tool("finish", "Submit your claim.", panel._obj(
        {"claim": {"type": "string", "enum": ["reduced", "no_evidence", "increased"]},
         "effect_pct": {"type": "number"}, "ci_low_pct": {"type": "number"}, "ci_high_pct": {"type": "number"},
         "method": {"type": "string"}}, ["claim", "effect_pct", "ci_low_pct", "ci_high_pct", "method"]), finish))
    task = (f"Program {pid}: {len(site_df[explore])} sites" + (" (half of the program; the rest are held out)" if gated else "")
            + f", installed between {T._label(int(site_df['month'].min()))} and {T._label(int(site_df['month'].max()))}."
            " Did it reduce crashes?")
    try:
        run = run_agent(client, model, INSTRUCTIONS.format(outcome=outcome, first=first, last=last,
                                                           gate=GATE if gated else "", data=getattr(sbx, "data", "/data")),
                        task, tools, exp["agentic"]["max_turns"], exp["agentic"]["budget_usd"], effort="medium",
                        tag=f"{tag} {'gated' if gated else 'ungated'} {pid}", escalate_after=4)
    finally:
        sbx.close()
    return {"program": pid, "gated": gated, "executor": executor, "claim": state["claim"], "gate": state["gate"], "stopped": run.stopped,
            "turns": run.turns, "code_runs": sbx.runs, "usd": round(run.usd, 5), "refusals": run.refusals,
            "steps": [{"tool": s.tool, "arguments": s.arguments if s.tool != "run_python" else
                       {"code": s.arguments.get("code", "")[:4000]},
                       "result": s.result if s.tool != "run_python" else {"output": str(s.result.get("output", ""))[:2000]}}
                      for s in run.steps]}
