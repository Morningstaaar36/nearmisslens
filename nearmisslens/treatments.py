"""Did the city's own treatments work? The study engine behind NML-Bench T11 and the causal gate.

A comparison-group before/after study (Hauer, Observational Before-After Studies in Road Safety, 1997) of any dated
treatment program in the open-data registry (a project adapter with a date field) against the city's police-reported
crashes (its crash adapter). For each treated site the crashes within the radius in the window after the install
month are compared with what the window before predicts, scaled by the change at comparison sites over the same
months:
    pi = before x r,  r = comparison after / comparison before,  theta = sum(after) / sum(pi)
theta < 1 means fewer crashes than expected. Comparison groups: the program's not-yet-treated sites (the city also
chose them, but installed them later) or the citywide trend away from any treatment. A placebo with a fake install
date before the real one tests for trend or selection bias.

A study is a JSON spec in validation/studies/: the city, the programs, the design and the rule are fixed in a file
before it runs, and nothing about a city is written in code. A program passes the gate only if its registered rule is
met and every placebo for its primary comparison shows no change."""
from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import context, opendata
from .config import ROOT, SETTINGS
from .evaluate import RESULTS_DIR

STUDIES = ROOT / "validation" / "studies"
OUTCOMES = ("pedestrian", "injury", "motorist_only")
SEED, N_BOOT = 0, 2000
PAGE = 500_000
_TREES: dict = {}


def _month(d) -> int | None:
    """Months since year 0 (year * 12 + month - 1), from a date, an ISO date string or epoch milliseconds."""
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return None
    day = opendata._date(d)
    return day.year * 12 + day.month - 1 if day and day.year >= 1900 else None


def _label(m: int) -> str:
    return f"{m // 12}-{m % 12 + 1:02d}"


def origin(city: str) -> tuple[float, float]:
    """The centre of the city's bounding box: the origin of its local metric projection."""
    s, w, n, e = opendata.city(city)["bbox"]
    return (s + n) / 2, (w + e) / 2


def xy(lat, lon, org: tuple[float, float]) -> np.ndarray:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return np.column_stack([(lon - org[1]) * 111_320 * np.cos(np.radians(org[0])), (lat - org[0]) * 110_574])


# ---------------------------------------------------------------- data: crashes and treatment programs, any city

def crash_adapter(city: str) -> dict:
    found = opendata.adapters_of(city, "crash")
    if not found:
        raise ValueError(f"no crash dataset is registered for {city}; run the data agent (nml discover LAT LON)")
    return found[0]


def _crash_fields(a: dict) -> list[str]:
    modes = [f for m in (a.get("injured", {}), a.get("killed", {})) for fs in m.values() for f in fs]
    return [f for f in dict.fromkeys([a.get("id_field"), a["date_field"], a.get("lat_field"), a.get("lon_field"),
                                      *modes, *a.get("serious_injured", []), *a.get("crash_type_fields", []),
                                      *a.get("pedestrian_involved", []), *a.get("cyclist_involved", [])]) if f]


def download(a: dict, d: Path) -> None:
    """The whole crash table, in pages of CSV in the data directory (free, no key)."""
    import httpx
    if SETTINGS.replay:
        raise FileNotFoundError(f"no crash pages in {d} (replay mode does not download)")
    d.mkdir(parents=True, exist_ok=True)
    fields = _crash_fields(a)
    if a["platform"] == "socrata":
        url = a["endpoint"].replace(".json", ".csv")
        where = f"{a['lat_field']} IS NOT NULL" if a.get("lat_field") else f"{a['geo_field']} IS NOT NULL"
        for k in range(100):
            params = {"$select": ",".join(fields + ([a["geo_field"]] if not a.get("lat_field") else [])),
                      "$where": where, "$order": a.get("id_field") or ":id", "$limit": PAGE, "$offset": k * PAGE}
            with httpx.Client(headers=context.UA, timeout=900) as c:
                r = c.get(url, params=params)
            r.raise_for_status()
            if r.text.count("\n") <= 1:
                break
            (d / f"page_{k}.csv").write_text(r.text)
        return
    # ArcGIS: keyset paging on the object id (offset paging stops early on some servers)
    oid = a.get("oid_field", "OBJECTID")
    last, k, buf = -1, 0, []
    with httpx.Client(headers=context.UA, timeout=300) as c:
        while True:
            r = c.get(f"{a['endpoint']}/query", params={
                "where": f"({a.get('where', '1=1')}) AND {oid} > {last}", "outFields": ",".join(fields + [oid]),
                "returnGeometry": "true", "outSR": 4326, "f": "json", "orderByFields": f"{oid} ASC",
                "resultRecordCount": a.get("page_size", 1000)})
            r.raise_for_status()
            feats = r.json().get("features", [])
            for f in feats:
                g = f.get("geometry") or {}
                buf.append({**f.get("attributes", {}), "_lat": g.get("y"), "_lon": g.get("x")})
            if feats:
                last = max(f["attributes"][oid] for f in feats)
            if buf and (len(buf) >= PAGE or not feats):
                pd.DataFrame(buf).to_csv(d / f"page_{k}.csv", index=False)
                buf, k = [], k + 1
            if not feats:
                break


def crashes(city: str, org: tuple[float, float] | None = None) -> pd.DataFrame:
    """Every geolocated crash of the city, as month, outcome flags and local x/y in metres."""
    a = crash_adapter(city)
    d = SETTINGS.data_dir / "crashes" / a["id"]
    if not sorted(d.glob("page_*.csv")):
        download(a, d)
    df = pd.concat([pd.read_csv(p, low_memory=False) for p in sorted(d.glob("page_*.csv"))], ignore_index=True)
    if a.get("id_field") in df:
        df = df.drop_duplicates(a["id_field"])
    lat = df[a["lat_field"]] if a.get("lat_field") in df else df.get("_lat")
    lon = df[a["lon_field"]] if a.get("lon_field") in df else df.get("_lon")
    df = df.assign(_lat=pd.to_numeric(lat, errors="coerce"), _lon=pd.to_numeric(lon, errors="coerce"))
    s, w, n, e = opendata.city(city)["bbox"]
    df = df[df["_lat"].between(s, n) & df["_lon"].between(w, e)].copy()

    def total(fields: list[str]) -> pd.Series:
        cols = [c for c in fields if c in df]
        return df[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) if cols else pd.Series(0, df.index)
    inj, kil = a.get("injured", {}), a.get("killed", {})
    ped = total(inj.get("pedestrian", []) + kil.get("pedestrian", []))
    cyc = total(inj.get("cyclist", []) + kil.get("cyclist", []))
    hurt = total([f for m in (inj, kil) for fs in m.values() for f in fs])
    injury = (hurt > 0) | (total(a.get("serious_injured", [])) > 0)
    if "pedestrian" not in inj and a.get("pedestrian_involved"):  # people involved by mode, injuries in total
        ped = ((total(a["pedestrian_involved"]) > 0) & injury).astype(int)
        cyc = ((total(a.get("cyclist_involved", [])) > 0) & injury).astype(int)
    elif "pedestrian" not in inj:  # injuries not split by mode: the crash type says who was involved
        kind = df[[c for c in a.get("crash_type_fields", []) if c in df]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        ped = (kind.str.contains("pedestrian") & injury).astype(int)
        cyc = ((kind.str.contains("cycl") | kind.str.contains("bicycl")) & injury).astype(int)
    when = df[a["date_field"]]
    when = pd.to_datetime(when, unit="ms", errors="coerce") if pd.api.types.is_numeric_dtype(when) \
        else pd.to_datetime(when.astype(str).str[:10], errors="coerce")
    out = pd.DataFrame({"month": when.dt.year * 12 + when.dt.month - 1, "pedestrian": ped > 0, "injury": injury,
                        "motorist_only": injury & (ped == 0) & (cyc == 0)}).dropna(subset=["month"])
    out["month"] = out["month"].astype(int)
    # the record's coverage: from the first to the last month with at least a tenth of the median monthly count, so
    # stray dates (DC's table has some from 1825) do not stretch the study period
    per = out["month"].value_counts()
    full = per[per >= 0.1 * per.median()].index
    out = out[out["month"].between(full.min(), full.max())]
    p = xy(df.loc[out.index, "_lat"], df.loc[out.index, "_lon"], org or origin(city))
    out = out.assign(x=p[:, 0], y=p[:, 1])
    return out.reset_index(drop=True)


def program_points(a: dict) -> pd.DataFrame:
    """The dated sites of a treatment program (a project adapter with a date field)."""
    rows = opendata.rows_all(a)
    pts = [{"lat": r["_lat"], "lon": r["_lon"], "month": _month(r.get(a["date_field"]))} for r in rows
           if r.get("_lat") is not None]
    return pd.DataFrame(pts, columns=["lat", "lon", "month"]).dropna(subset=["month"]).astype({"month": int})


def sites(points: pd.DataFrame, merge_m: float, org: tuple[float, float]) -> pd.DataFrame:
    """Points within merge_m of each other (chained) are one site, dated by the earliest install and placed there."""
    p = xy(points["lat"], points["lon"], org)
    parent = np.arange(len(points))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in cKDTree(p).query_pairs(merge_m):
        parent[root(i)] = root(j)
    groups = np.array([root(i) for i in range(len(points))])
    g = points.assign(group=groups, x=p[:, 0], y=p[:, 1]).sort_values("month", kind="stable").groupby("group")
    first = g.first()
    first["points"] = g.size()
    return first.reset_index(drop=True)[["lat", "lon", "x", "y", "month", "points"]]


# ---------------------------------------------------------------- the comparison-group estimator

def monthly_counts(site_df: pd.DataFrame, cr: pd.DataFrame, m0: int, m1: int, radius_m: float) -> dict[str, np.ndarray]:
    """Crashes within radius_m of each site per month (m0..m1) for each outcome: arrays of sites x months."""
    key = (id(cr), len(cr))
    if key not in _TREES:  # one index per crash table (the calibrated gate runs hundreds of studies on it)
        _TREES.clear()
        _TREES[key] = cKDTree(cr[["x", "y"]].to_numpy())
    near = _TREES[key].query_ball_point(site_df[["x", "y"]].to_numpy(), radius_m)
    si = np.repeat(np.arange(len(site_df)), [len(n) for n in near])
    ci = np.concatenate([np.asarray(n, int) for n in near]) if len(si) else np.zeros(0, int)
    months = cr["month"].to_numpy()[ci] - m0
    ok = (months >= 0) & (months <= m1 - m0)
    out = {}
    for o in OUTCOMES:
        sel = ok & cr[o].to_numpy()[ci]
        mat = np.zeros((len(site_df), m1 - m0 + 1), np.int32)
        np.add.at(mat, (si[sel], months[sel]), 1)
        out[o] = mat
    return out


def _window_sum(mat: np.ndarray, start: np.ndarray, length: int) -> np.ndarray:
    """Per row, the sum of `length` months from column start[i] (cumulative sums, so any start is O(1))."""
    c = np.concatenate([np.zeros((mat.shape[0], 1), np.int64), np.cumsum(mat, axis=1)], axis=1)
    rows = np.arange(mat.shape[0])
    return c[rows, start + length] - c[rows, start]


def estimate(after: np.ndarray, before: np.ndarray, cohort: np.ndarray, cg_after: np.ndarray, cg_before: np.ndarray,
             cg_eligible: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """theta = sum(after) / sum(before x r_cohort). cg_after/cg_before/cg_eligible are cohorts x comparison sites;
    the bootstrap resamples treated sites and (when there is more than one comparison unit) comparison sites."""
    ca, cb = cg_after * cg_eligible, cg_before * cg_eligible
    # a cohort with no comparison crashes before has no counterfactual: its treated sites are left out, not set to 0
    usable = cb.sum(1) > 0
    dropped = int((~usable[cohort]).sum())
    keep = usable[cohort]
    after, before, cohort = after[keep], before[keep], cohort[keep]
    r = ca.sum(1) / np.maximum(cb.sum(1), 1e-9)
    pi = before * r[cohort]
    if pi.sum() <= 0:
        return {"theta": None, "ci95": None, "sites": int(len(after)), "after": int(after.sum()),
                "before": int(before.sum()), "expected_after": 0.0, "dropped_no_comparison": dropped}
    theta = after.sum() / pi.sum()
    if n_boot == 0:  # point estimate only (the calibrated gate's fake programs)
        return {"theta": round(float(theta), 4), "ci95": None, "sites": int(len(after)), "after": int(after.sum()),
                "before": int(before.sum()), "expected_after": round(float(pi.sum()), 1), "dropped_no_comparison": dropped}
    rng = np.random.default_rng(seed)
    nt, nc = len(after), ca.shape[1]
    boots = np.empty(n_boot)
    for b in range(n_boot):
        w = rng.multinomial(nt, np.full(nt, 1 / nt))
        if nc > 1:
            v = rng.multinomial(nc, np.full(nc, 1 / nc))
            cbv = cb @ v
            rb = np.where(cbv > 0, (ca @ v) / np.maximum(cbv, 1e-9), r)  # a resample that drops a cohort's comparisons
        else:
            rb = r
        boots[b] = (w * after).sum() / max((w * before * rb[cohort]).sum(), 1e-9)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"theta": round(float(theta), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "change_pct": round(100 * (float(theta) - 1), 1), "sites": int(nt), "after": int(after.sum()),
            "before": int(before.sum()), "expected_after": round(float(pi.sum()), 1),
            "cg_ratio_median": round(float(np.median(r[np.unique(cohort)])), 3), "dropped_no_comparison": dropped}


def _not_yet_treated(cohorts: np.ndarray, length: int, prog: pd.DataFrame, prog_nb: list[np.ndarray]) -> np.ndarray:
    """cohorts x program sites: eligible as comparison for a cohort (install month c) when installed after the
    cohort's after window ends (c + length) and no other site of the program within the neighbour distance was
    installed by then."""
    end = cohorts[:, None] + length
    later = prog["month"].to_numpy()[None, :] > end
    first_nb = np.array([n.min() if len(n) else 10 ** 6 for n in prog_nb])
    clean = first_nb[None, :] > end
    return later & clean


def evaluate_suite(spec: dict, cr: pd.DataFrame, points: dict[str, pd.DataFrame], org: tuple[float, float]) -> dict:
    """Run a study spec on given crashes and program points (adapter id -> points), with no I/O."""
    merge_m, radius_m, nb_m, window = spec["merge_m"], spec["radius_m"], spec["neighbour_m"], spec["window_months"]
    outcomes = tuple(spec.get("outcomes") or OUTCOMES)
    m0, m1 = int(cr["month"].min()), int(cr["month"].max())
    exclude_ids = spec.get("exclude_near") or list(points)
    site_of = {k: sites(v, merge_m, org) for k, v in points.items()}
    ex = [site_of[k] for k in exclude_ids]
    all_xy = np.vstack([s[["x", "y"]].to_numpy() for s in ex])
    all_month = np.concatenate([s["month"].to_numpy() for s in ex])
    city = {}
    if any("citywide" in p["comparisons"] for p in spec["programs"]):
        # citywide trend (comparison group b): crashes more than nb_m from any treatment site, any date
        dist, _ = cKDTree(all_xy).query(cr[["x", "y"]].to_numpy(), distance_upper_bound=nb_m)
        away = cr[np.isinf(dist)]
        city = {o: np.bincount(away.loc[away[o], "month"].to_numpy() - m0, minlength=m1 - m0 + 1)[None, :]
                for o in outcomes}
    out = {"id": spec["id"], "city": spec["city"], "registered": spec.get("registered"), "spec": spec,
           "data": {"crashes": int(len(cr)), "crash_months": [_label(m0), _label(m1)], "programs": {}},
           "runs": {}, "gates": {}}

    for prog_spec in spec["programs"]:
        key, aid = prog_spec["key"], prog_spec["adapter"]
        prog = site_of[aid]
        counts = monthly_counts(prog, cr, m0, m1, radius_m)
        # neighbours of each site among all treatment sites (itself excluded) and among the program's own sites
        offset = sum(len(site_of[k]) for k in exclude_ids[:exclude_ids.index(aid)]) if aid in exclude_ids else None
        near = cKDTree(all_xy).query_ball_point(prog[["x", "y"]].to_numpy(), nb_m)
        nb_all = [all_month[[j for j in n if offset is None or j != offset + i]] for i, n in enumerate(near)]
        near_own = cKDTree(prog[["x", "y"]].to_numpy()).query_ball_point(prog[["x", "y"]].to_numpy(), nb_m)
        nb_own = [prog["month"].to_numpy()[[j for j in n if j != i]] for i, n in enumerate(near_own)]
        out["data"]["programs"][key] = {"adapter": aid, "points": int(len(points[aid])), "sites": int(len(prog))}

        def study(comparison, shift=0, length=window, only=None):
            if prog_spec["treated"] == "auto":  # three years after the first crash month to three years before the last
                lo, hi = m0 + window, m1 - window
            else:
                lo, hi = (_month(d) for d in prog_spec["treated"])
            real = prog["month"].to_numpy()
            fake = real - shift
            # windows [m - length, m - 1] and [m + 1, m + length] around the (possibly fake) install month m
            excl = np.array([((n >= r - shift - length) & (n <= r + (length if not shift else -1))).any()
                             for n, r in zip(nb_all, real)])
            treated = (real >= lo) & (real <= hi) & (fake - length >= m0) & (fake + length <= m1)
            keep = treated & ~excl & (only if only is not None else True)
            idx = np.flatnonzero(keep)
            res = {"treated_in_range": int(treated.sum()), "excluded_neighbour_treatment": int((treated & excl).sum()),
                   "_keep": keep}
            if not len(idx):
                return {**res, **{o: None for o in outcomes}, "install_months": None}
            cohorts = np.unique(fake[idx])
            cohort_of = np.searchsorted(cohorts, fake[idx])
            for o in outcomes:
                mat = counts[o]
                before = _window_sum(mat[idx], fake[idx] - length - m0, length)
                after = _window_sum(mat[idx], fake[idx] + 1 - m0, length)
                if comparison == "not_yet_treated":
                    elig = _not_yet_treated(cohorts, length, prog, nb_own)
                    cb = np.stack([_window_sum(mat, np.full(len(prog), c - length - m0), length) for c in cohorts])
                    ca = np.stack([_window_sum(mat, np.full(len(prog), c + 1 - m0), length) for c in cohorts])
                    est = estimate(after, before, cohort_of, ca, cb, elig, n_boot=spec.get("n_boot", N_BOOT))
                    est["cg_sites_min"] = int(elig.sum(1).min())
                    est["cg_sites_median"] = int(np.median(elig.sum(1)))
                else:
                    cm = city[o]
                    cb = np.array([[_window_sum(cm, np.array([c - length - m0]), length)[0]] for c in cohorts])
                    ca = np.array([[_window_sum(cm, np.array([c + 1 - m0]), length)[0]] for c in cohorts])
                    est = estimate(after, before, cohort_of, ca, cb, np.ones_like(ca, bool), n_boot=spec.get("n_boot", N_BOOT))
                res[o] = est
            res["install_months"] = [_label(int(cohorts.min()) + shift), _label(int(cohorts.max()) + shift)]
            return res

        # the naive estimate (after / before at the treated sites, no comparison group), for contrast with the gate
        lo_, hi_ = (m0 + window, m1 - window) if prog_spec["treated"] == "auto" else \
            tuple(_month(d) for d in prog_spec["treated"])
        real = prog["month"].to_numpy()
        ok = np.flatnonzero((real >= lo_) & (real <= hi_) & (real - window >= m0) & (real + window <= m1))
        naive = {}
        for o in outcomes:
            b = _window_sum(counts[o][ok], real[ok] - window - m0, window)
            a = _window_sum(counts[o][ok], real[ok] + 1 - m0, window)
            rng = np.random.default_rng(SEED)
            boots = [(w * a).sum() / max((w * b).sum(), 1)
                     for w in rng.multinomial(len(ok), np.full(len(ok), 1 / max(len(ok), 1)), size=spec.get("n_boot", N_BOOT))] if len(ok) and spec.get("n_boot", N_BOOT) else []
            t = a.sum() / max(b.sum(), 1)
            naive[o] = {"theta": round(float(t), 3), "change_pct": round(100 * (float(t) - 1), 1), "sites": int(len(ok)),
                        "after": int(a.sum()), "before": int(b.sum()),
                        "ci95": [round(float(v), 3) for v in np.percentile(boots, [2.5, 97.5])] if boots else None}
        out["naive"] = {**out.get("naive", {}), key: naive}
        pl = spec.get("placebo")
        for comparison in prog_spec["comparisons"]:
            main = study(comparison)
            out["runs"][f"{key}_{comparison}"] = main
            if not pl:  # no placebo runs (the calibrated gate's fake programs)
                continue
            out["runs"][f"{key}_placebo_{comparison}"] = study(comparison, pl["shift_months"], pl["window_months"])
            if comparison in prog_spec.get("placebo_same_sites", []):
                out["runs"][f"{key}_placebo_same_sites_{comparison}"] = study(
                    comparison, pl["shift_months"], pl["window_months"], only=main["_keep"])
        if prog_spec["primary"] == "auto":  # fixed by data availability: sites treated later, if 100 sites have them
            nyt = (out["runs"].get(f"{key}_not_yet_treated") or {}).get(prog_spec["outcome"]) or {}
            prog_spec = {**prog_spec, "primary": "not_yet_treated" if (nyt.get("sites") or 0) >= 100 else "citywide"}
        out["gates"][key] = gate(out["runs"], prog_spec)
    for v in out["runs"].values():
        v.pop("_keep", None)
    return out


def gate(runs: dict, prog_spec: dict) -> dict:
    """The causal gate for one program: the registered rule on the primary comparison (the interval for the outcome
    entirely below 1) and every placebo of that comparison showing no change (its interval includes 1)."""
    key, comp, o = prog_spec["key"], prog_spec["primary"], prog_spec["outcome"]
    main = (runs.get(f"{key}_{comp}") or {}).get(o) or {}
    placebos = [k for k in (f"{key}_placebo_{comp}", f"{key}_placebo_same_sites_{comp}") if k in runs]
    ci = main.get("ci95")
    rule = bool(ci and ci[1] < 1)
    bad = [k for k in placebos
           if (runs[k].get(o) or {}).get("ci95") and not (runs[k][o]["ci95"][0] <= 1 <= runs[k][o]["ci95"][1])]
    reason = None if rule and not bad else ("the effect's interval includes no change" if not rule
                                            else "a placebo date before the install shows a change too")
    return {"countermeasure": prog_spec.get("countermeasure"), "treatment": prog_spec.get("label", key),
            "outcome": o, "primary": f"{key}_{comp}", "placebos": placebos, "rule_met": rule,
            "placebo_ok": not bad, "passed": rule and not bad, "reason": reason}


# ---------------------------------------------------------------- registered suites and what they feed

def load_spec(name: str) -> dict:
    return json.loads((STUDIES / f"{name}.json").read_text())


def run_suite(spec: dict) -> dict:
    """Load the city's crashes and programs from the registry, run the spec, add the brief's CMF for each program's
    countermeasure, and save the result."""
    city = spec["city"]
    org = origin(city)
    cr = crashes(city, org)
    ids = list(dict.fromkeys([p["adapter"] for p in spec["programs"]] + (spec.get("exclude_near") or [])))
    points = {aid: program_points(opendata.adapter(aid)) for aid in ids}
    out = evaluate_suite(spec, cr, points, org)
    for p in spec["programs"]:
        if p.get("countermeasure"):
            out["gates"][p["key"]]["brief_cmf"] = brief_cmf(p["countermeasure"], p["outcome"])
    if spec.get("projection"):
        out["projection"] = projection(spec, out, cr, points, org)
    out["run_date"] = dt.date.today().isoformat()
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"study_{spec['id']}.json"
    keep_fake_rank(out, json.loads(path.read_text()) if path.exists() else {})
    path.write_text(json.dumps(out, indent=1, default=float))
    return out


def keep_fake_rank(new: dict, old: dict) -> None:
    """The rank among fake programs (written by a separate, slower run: falsify.rank_studies) survives a rerun of the
    study when the program's result is unchanged; a changed result drops it, so a stale rank is never shown."""
    for key, g in new.get("gates", {}).items():
        og = (old.get("gates") or {}).get(key) or {}
        if "fake_rank" not in og:
            continue
        cur = (new["runs"].get(g.get("primary")) or {}).get(g.get("outcome")) or {}
        prev = ((old.get("runs") or {}).get(og.get("primary")) or {}).get(og.get("outcome")) or {}
        if cur.get("theta") == prev.get("theta") and cur.get("ci95") == prev.get("ci95"):
            g["fake_rank"] = og["fake_rank"]


def brief_cmf(countermeasure: str, outcome: str) -> list[dict]:
    """The CMF Clearinghouse record the brief estimates this countermeasure with for the outcome's crash population,
    at the site control its curated records are for."""
    from . import countermeasures
    item = next((i for i in countermeasures.psc_items() if i["name"] == countermeasure), {})
    pop = "pedestrian" if outcome == "pedestrian" else "all"
    controls = {c for e in item.get("cmf_allow", []) for c in e["control"]} - {"any"} or {"unknown"}
    out = []
    for control in sorted(controls):
        sel = countermeasures.select(item, control, {pop: 1}, countermeasures.load_cmf())
        if sel["quantified"]:
            out.append({"cmf_id": sel["cmf_id"], "cmf": sel["cmf"], "stars": sel["stars"],
                        "crash_type": sel["cmf_crash_type"], "severity": sel["cmf_severity"], "control": control,
                        "chosen_by": sel["chosen_by"]})
    return out


def projection(spec: dict, out: dict, cr: pd.DataFrame, points: dict, org) -> dict:
    """Descriptive, added after T11: the city's listed priority intersections with no site of the program nearby, and
    the outcome crashes (each counted once, over the last `months` months of records) that the program's measured
    effect suggests it would avoid there. A site still needs an engineer's check."""
    from . import harm
    pj = spec["projection"]
    prog_spec = next(p for p in spec["programs"] if p["key"] == pj["program"])
    effect = out["runs"][f"{pj['program']}_{prog_spec['primary']}"][prog_spec["outcome"]]
    rows = pd.DataFrame(json.loads((RESULTS_DIR / "bench" / pj["junctions_from"]).read_text())["rows"])
    ixy = xy(rows["lat"], rows["lon"], org)
    pts = points[prog_spec["adapter"]]
    dist, _ = cKDTree(xy(pts["lat"], pts["lon"], org)).query(ixy, distance_upper_bound=pj["near_m"])
    none = np.flatnonzero(~np.isfinite(dist))
    m1 = int(cr["month"].max())
    m0 = m1 - pj["months"] + 1
    near = cKDTree(cr[["x", "y"]].to_numpy()).query_ball_point(ixy[none], pj["radius_m"])
    idx = np.unique(np.concatenate([np.asarray(n, int) for n in near])) if len(none) else np.zeros(0, int)
    o = prog_spec["outcome"]
    sel = idx[cr[o].to_numpy()[idx] & (cr["month"].to_numpy()[idx] >= m0)]
    per_year = len(sel) / (pj["months"] / 12)
    theta, (lo, hi) = effect["theta"], effect["ci95"]
    avoided = [per_year * (1 - t) for t in (theta, hi, lo)]
    return {"intersections": int(len(rows)), "without_program": int(len(none)),
            "without_program_plan_gap": int(rows.loc[none, "plan_gap"].fillna(False).sum()),
            "months": [_label(m0), _label(m1)], "outcome_crashes": int(len(sel)),
            "per_year": round(per_year, 1), "avoided_per_year": round(avoided[0], 1),
            "avoided_per_year_interval": [round(avoided[1], 1), round(avoided[2], 1)],
            "harm_avoided_usd_per_year": round(avoided[0] * harm.INJURY_CRASH_USD, -5),
            "names": sorted(rows.loc[none, "name"].tolist())}


def results() -> list[dict]:
    files = tuple((str(p), p.stat().st_mtime_ns) for p in sorted((RESULTS_DIR / "bench").glob("study_*.json")))
    return _read_results(files)


@lru_cache(maxsize=4)
def _read_results(files: tuple) -> list[dict]:
    return [json.loads(Path(p).read_text()) for p, _ in files]


OUTCOME_WORDS = {"pedestrian": "pedestrian injury crashes", "injury": "injury crashes",
                 "motorist_only": "injury crashes with no pedestrian or cyclist hurt"}
# what the city's own record says about a program it ran; never "failed" or "doesn't work": an effect not shown in
# the record is not shown to be absent
NOT_SUPPORTED = ("earlier trend", "not shown", "worse")


def pct(x: float) -> int:
    """Percent rounded half away from zero (Python's round() sends -32.5 to -32)."""
    x = round(float(x), 6)  # 100 * (0.675 - 1) is -32.49999... in floating point
    return int(np.sign(x) * np.floor(abs(x) + 0.5))


def _status(g: dict, main: dict) -> str:
    ci = main.get("ci95")
    if g.get("passed"):
        return "worked"
    if g.get("rule_met") and not g.get("placebo_ok"):
        return "earlier trend"
    if ci and ci[0] > 1:
        return "worse"
    return "not shown"


def programs(city: str | None = None) -> list[dict]:
    """Every program a registered study tested, with what the city's own record says about it: worked (the causal
    gate passed), earlier trend (a drop, but a placebo date before the install shows one too), worse (crashes rose),
    or not shown (the interval includes no change)."""
    out = []
    for res in results():
        if city and res.get("city") != city:
            continue
        specs = {p["key"]: p for p in (res.get("spec") or {}).get("programs", [])}
        for key, g in (res.get("gates") or {}).items():
            main = (res.get("runs", {}).get(g["primary"]) or {}).get(g["outcome"]) or {}
            if not main.get("ci95"):
                continue
            spec = specs.get(key, {})
            naive = ((res.get("naive") or {}).get(key) or {}).get(g["outcome"]) or {}
            status = _status(g, main)
            label, words = g.get("treatment") or key, OUTCOME_WORDS.get(g["outcome"], g["outcome"])
            lo, hi = (pct(100 * (v - 1)) for v in main["ci95"])
            ch = pct(100 * (main["theta"] - 1))
            text = {"worked": f"{words} changed {ch:+d}% (95% interval {lo:+d}% to {hi:+d}%) at {main['sites']:,} "
                              "sites against sites treated later or the citywide trend, and a placebo date shows nothing",
                    "earlier trend": f"a simple before/after says {pct(naive.get('change_pct', ch)):+d}%, but a "
                                     "placebo date before the work shows a drop too, so the decline cannot be credited "
                                     "to the program",
                    "worse": f"{words} rose {ch:+d}% (95% interval {lo:+d}% to {hi:+d}%) at {main['sites']:,} sites",
                    "not shown": f"at {main['sites']:,} sites the change in {words} ({ch:+d}%, 95% interval {lo:+d}% "
                                 f"to {hi:+d}%) could be zero"}[status]
            out.append({"city": res.get("city"), "study": res["id"], "program": key, "label": label,
                        "adapter": spec.get("adapter"), "countermeasure": g.get("countermeasure"),
                        "outcome": g["outcome"], "status": status, "theta": main["theta"], "ci95": main["ci95"],
                        "sites": main["sites"], "naive_change_pct": naive.get("change_pct"),
                        "fake_rank": (g.get("fake_rank") or {}).get("rank"), "text": text,
                        "source": f"NML-Bench {res['id']} (validation/BENCH.md)"})
    return out


def distinct_programs(city: str | None = None) -> list[dict]:
    """programs(), with one entry per city, countermeasure and outcome: a registered study is kept over a run the
    program agent set up itself (study ids starting 'auto'), and the other runs are listed under 'also_tested'."""
    out: dict[tuple, dict] = {}
    for p in sorted(programs(city), key=lambda p: (str(p.get("study", "")).startswith("auto"), str(p.get("study", "")))):
        k = (p.get("city"), p.get("countermeasure") or p.get("program") or p.get("label"), p.get("outcome"))
        if k in out:
            out[k].setdefault("also_tested", []).append({"study": p.get("study"), "sites": p.get("sites"),
                                                         "status": p.get("status")})
        else:
            out[k] = dict(p)
    return list(out.values())


def program_status(city: str | None, countermeasure: str | None = None, adapter: str | None = None) -> dict:
    """The city's verdict on one countermeasure (or one program dataset): a study that passed wins, otherwise the
    largest study; 'untested' when no registered study covers it."""
    found = [p for p in programs(city) if (countermeasure and p["countermeasure"] == countermeasure)
             or (adapter and p["adapter"] == adapter)]
    if not found:
        return {"status": "untested", "countermeasure": countermeasure, "adapter": adapter, "city": city}
    return max(found, key=lambda p: (p["status"] == "worked", p["sites"]))


def repeat_risk(city: str | None, projects: list[dict]) -> list[dict]:
    """Programs this corner already got whose citywide effect the city's own record does not support: doing the same
    again here is not backed by evidence. One flag per program, with the year it arrived."""
    flags = {}
    for pr in projects:
        pr = {**pr, "year": opendata.known_year(pr.get("year"))}  # reports saved before placeholder dates were dropped
        st = program_status(city, adapter=pr.get("dataset"))
        if st["status"] not in NOT_SUPPORTED:
            continue
        key = st["adapter"]
        if key not in flags or (pr.get("year") or 9999) < (flags[key].get("year") or 9999):
            flags[key] = {"program": st["label"], "year": pr.get("year"), "status": st["status"], "dataset": key,
                          "study": st["study"], "source": st["source"], "theta": st.get("theta"),
                          "ci95": st.get("ci95"), "sites": st.get("sites"),
                          "text": f"This corner got {st['label']}{' in ' + str(pr['year']) if pr.get('year') else ''}. "
                                  f"Across the city: {st['text']}. Repeating it here is not supported by the city's "
                                  "own record."}
    return list(flags.values())


def local_evidence(city: str | None, countermeasure: str) -> dict | None:
    """What a registered study measured for this countermeasure at the city's own past installs, if it passed the
    causal gate (rule met and no placebo change); None otherwise."""
    for res in results():
        if res.get("city") != city:
            continue
        for g in res.get("gates", {}).values():
            if g.get("countermeasure") != countermeasure or not g.get("passed"):
                continue
            main = res["runs"][g["primary"]][g["outcome"]]
            placebo = res["runs"][g["placebos"][-1]][g["outcome"]] if g["placebos"] else None
            lo, hi = (pct(100 * (1 - v)) for v in reversed(main["ci95"]))
            outcome = OUTCOME_WORDS.get(g["outcome"], g["outcome"])
            return {"theta": main["theta"], "ci95": main["ci95"], "sites": main["sites"], "outcome": g["outcome"],
                    "outcome_words": outcome.lower(),
                    "placebo_theta": placebo and placebo["theta"], "placebo_ci95": placebo and placebo["ci95"],
                    "study": res["id"], "source": f"NML-Bench {res['id']} (validation/BENCH.md)",
                    "fake_rank": (g.get("fake_rank") or {}).get("rank"),
                    "text": f"{outcome} fell {pct(-main['change_pct'])}% (95% interval {lo}-{hi}%) at "
                            f"{main['sites']:,} intersections after the city installed it, against sites that got "
                            "it later; a placebo date before the install shows no drop."
                            + (f" A stricter check is less sure: {pct(100 * (1 - g['fake_rank']['rank']))}% of 200 "
                               "fake programs show a smaller drop." if (g.get("fake_rank") or {}).get("rank") is not None else "")}
    return None


def auto_spec(city: str, found_by: tuple[str, ...] = ("program agent",)) -> dict:
    """T13's registered design applied to every dated program the program agent found for a city (exploratory: the
    programs were not known when T13 was registered)."""
    progs = [a for a in opendata.adapters_of(city, "project")
             if a.get("date_field") and (a.get("provenance") or {}).get("found_by") in found_by]
    if not progs:
        raise ValueError(f"no agent-found programs for {city}; run nml programs {city}")
    t13 = {"merge_m": 30, "radius_m": 50, "neighbour_m": 100, "window_months": 36,
           "placebo": {"shift_months": 19, "window_months": 18}}
    return {"id": f"auto_{city}", "city": city, "title": f"Programs found by the agent in {opendata.city(city)['name']}",
            "registered": "exploratory: T13's registered design, applied to programs the program agent found",
            **t13, "exclude_near": [a["id"] for a in progs],
            "programs": [{"key": re.sub(r"[^a-z0-9]+", "_", a["label"].lower()).strip("_") + f"_{i}",
                          "adapter": a["id"], "label": a["label"], "countermeasure": a.get("countermeasure"),
                          "treated": "auto", "comparisons": ["not_yet_treated", "citywide"], "primary": "auto",
                          "outcome": "pedestrian", "placebo_same_sites": ["not_yet_treated", "citywide"]}
                         for i, a in enumerate(progs)]}
