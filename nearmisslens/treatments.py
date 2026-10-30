"""Did the city's own treatments work? (NML-Bench T11, registered in validation/BENCH_PREREG.md.)

A comparison-group before/after study (Hauer, Observational Before-After Studies in Road Safety, 1997) of New York's
Leading Pedestrian Intervals (LPIs), from open data: the LPI install dates, the turn traffic calming completion dates
and the police-reported crashes since July 2012. For each treated site the crashes within 50 m in the 36 months
after the install month are compared with what the 36 months before predict, scaled by the change at comparison
sites over the same months:
    pi = before x r,  r = comparison after / comparison before,  theta = sum(after) / sum(pi)
theta < 1 means fewer crashes than expected. The primary comparison group is the not-yet-treated LPI sites (the city
also chose them, but installed later); the sensitivity check is the citywide trend away from any treatment. A placebo
with a fake install date before the real one tests for trend or selection bias. The measured effect is set against
the CMF Clearinghouse values the brief ranks fixes with."""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import context
from .config import SETTINGS
from .evaluate import RESULTS_DIR

LPI = "https://data.cityofnewyork.us/resource/xc4v-ntf4.json"
TURN = "https://data.cityofnewyork.us/resource/sm2x-35i7.json"
CRASHES = "https://data.cityofnewyork.us/resource/h9gi-nx95.csv"
CRASH_FIELDS = ("collision_id", "crash_date", "latitude", "longitude", "number_of_pedestrians_injured",
                "number_of_pedestrians_killed", "number_of_cyclist_injured", "number_of_cyclist_killed",
                "number_of_motorist_injured", "number_of_motorist_killed")
LAT0, LON0 = 40.70, -73.95
MERGE_M, RADIUS_M, NEIGHBOUR_M = 30.0, 50.0, 100.0
WINDOW = 36
LPI_TREATED = ("2015-08-01", "2021-12-31")
TURN_TREATED = ("2016-01-01", "2021-12-31")
PLACEBO_WINDOW, PLACEBO_SHIFT = 18, 19  # the fake install month is 19 months early, so both windows end before it
OUTCOMES = ("pedestrian", "injury", "motorist_only")
SEED, N_BOOT = 0, 2000


def _month(d) -> int | None:
    """Months since year 0 (year * 12 + month - 1), from a date or an ISO date string."""
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return None
    s = str(d)[:7]
    try:
        y, m = int(s[:4]), int(s[5:7])
    except ValueError:
        return None
    return y * 12 + m - 1 if y >= 1900 else None


def _label(m: int) -> str:
    return f"{m // 12}-{m % 12 + 1:02d}"


def _xy(lat, lon) -> np.ndarray:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return np.column_stack([(lon - LON0) * 111_320 * np.cos(np.radians(LAT0)), (lat - LAT0) * 110_574])


def _points(url: str, date_field: str) -> pd.DataFrame:
    js, _ = context.fetch(url, {"$limit": 50000})
    rows = [{"lat": float(r["lat"]), "lon": float(r["long"]), "month": _month(r.get(date_field))}
            for r in js if r.get("lat") and r.get("long")]
    return pd.DataFrame(rows).dropna(subset=["month"]).astype({"month": int})


def sites(points: pd.DataFrame, merge_m: float = MERGE_M) -> pd.DataFrame:
    """Points within merge_m of each other (chained) are one site, dated by the earliest install and placed there."""
    xy = _xy(points["lat"], points["lon"])
    parent = np.arange(len(points))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in cKDTree(xy).query_pairs(merge_m):
        parent[root(i)] = root(j)
    groups = np.array([root(i) for i in range(len(points))])
    g = points.assign(group=groups, x=xy[:, 0], y=xy[:, 1]).sort_values("month", kind="stable").groupby("group")
    first = g.first()
    first["points"] = g.size()
    return first.reset_index(drop=True)[["lat", "lon", "x", "y", "month", "points"]]


def download(d, page: int = 500_000) -> None:
    """The crash table in pages of CSV (about 215 MB in all; free, no key)."""
    import httpx
    if SETTINGS.replay:
        raise FileNotFoundError(f"no crash pages in {d} (replay mode does not download)")
    d.mkdir(parents=True, exist_ok=True)
    for k in range(20):
        params = {"$select": ",".join(CRASH_FIELDS), "$where": "latitude IS NOT NULL AND latitude > 40",
                  "$order": "collision_id", "$limit": page, "$offset": k * page}
        with httpx.Client(headers=context.UA, timeout=600) as c:
            r = c.get(CRASHES, params=params)
        r.raise_for_status()
        if r.text.count("\n") <= 1:
            break
        (d / f"page_{k}.csv").write_text(r.text)


def crashes() -> pd.DataFrame:
    """Every geolocated crash since July 2012 (NYC Open Data h9gi-nx95), downloaded once to the data directory."""
    d = SETTINGS.data_dir / "nyc_crashes"
    if not sorted(d.glob("page_*.csv")):
        download(d)
    pages = sorted(d.glob("page_*.csv"))
    df = pd.concat([pd.read_csv(p, usecols=list(CRASH_FIELDS)) for p in pages], ignore_index=True)
    df = df.drop_duplicates("collision_id")
    s, w, n, e = context.CITIES["nyc"]
    df = df[df["latitude"].between(s, n) & df["longitude"].between(w, e)].copy()
    num = [c for c in CRASH_FIELDS if c.startswith("number_")]
    df[num] = df[num].fillna(0)
    ped = df["number_of_pedestrians_injured"] + df["number_of_pedestrians_killed"]
    cyc = df["number_of_cyclist_injured"] + df["number_of_cyclist_killed"]
    allv = ped + cyc + df["number_of_motorist_injured"] + df["number_of_motorist_killed"]
    out = pd.DataFrame({"month": df["crash_date"].str[:4].astype(int) * 12 + df["crash_date"].str[5:7].astype(int) - 1,
                        "pedestrian": ped > 0, "injury": allv > 0, "motorist_only": (allv > 0) & (ped == 0) & (cyc == 0)})
    xy = _xy(df["latitude"], df["longitude"])
    out["x"], out["y"] = xy[:, 0], xy[:, 1]
    return out.reset_index(drop=True)


def monthly_counts(site_df: pd.DataFrame, cr: pd.DataFrame, m0: int, m1: int) -> dict[str, np.ndarray]:
    """Crashes within RADIUS_M of each site per month (m0..m1) for each outcome: arrays of sites x months."""
    tree = cKDTree(cr[["x", "y"]].to_numpy())
    near = tree.query_ball_point(site_df[["x", "y"]].to_numpy(), RADIUS_M)
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


def _neighbour_dates(xy: np.ndarray, other_xy: np.ndarray, other_month: np.ndarray, same: bool) -> list[np.ndarray]:
    """For each point, the install months of the other sites within NEIGHBOUR_M (itself excluded when same)."""
    near = cKDTree(other_xy).query_ball_point(xy, NEIGHBOUR_M)
    return [other_month[[j for j in n if not (same and j == i)]] for i, n in enumerate(near)]


def estimate(after: np.ndarray, before: np.ndarray, cohort: np.ndarray, cg_after: np.ndarray, cg_before: np.ndarray,
             cg_eligible: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """theta = sum(after) / sum(before x r_cohort). cg_after/cg_before/cg_eligible are cohorts x comparison sites;
    the bootstrap resamples treated sites and (when there is more than one comparison unit) comparison sites."""
    ca, cb = cg_after * cg_eligible, cg_before * cg_eligible
    r = ca.sum(1) / np.maximum(cb.sum(1), 1e-9)
    pi = before * r[cohort]
    if pi.sum() <= 0:
        return {"theta": None, "ci95": None, "sites": int(len(after)), "after": int(after.sum()),
                "before": int(before.sum()), "expected_after": 0.0}
    theta = after.sum() / pi.sum()
    rng = np.random.default_rng(seed)
    nt, nc = len(after), ca.shape[1]
    boots = np.empty(n_boot)
    for b in range(n_boot):
        w = rng.multinomial(nt, np.full(nt, 1 / nt))
        if nc > 1:
            v = rng.multinomial(nc, np.full(nc, 1 / nc))
            rb = (ca @ v) / np.maximum(cb @ v, 1e-9)
        else:
            rb = r
        boots[b] = (w * after).sum() / max((w * before * rb[cohort]).sum(), 1e-9)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"theta": round(float(theta), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "change_pct": round(100 * (float(theta) - 1), 1), "sites": int(nt), "after": int(after.sum()),
            "before": int(before.sum()), "expected_after": round(float(pi.sum()), 1),
            "cg_ratio_median": round(float(np.median(r[np.unique(cohort)])), 3)}


def _not_yet_treated(cohorts: np.ndarray, length: int, lpi: pd.DataFrame, lpi_nb: list[np.ndarray]) -> np.ndarray:
    """cohorts x LPI sites: eligible as comparison for a cohort (install month c) when installed after the cohort's
    after window ends (c + length) and no other LPI within NEIGHBOUR_M was installed by then."""
    end = cohorts[:, None] + length
    later = lpi["month"].to_numpy()[None, :] > end
    first_nb = np.array([n.min() if len(n) else 10 ** 6 for n in lpi_nb])
    clean = first_nb[None, :] > end
    return later & clean


def analyse(points_lpi: pd.DataFrame, points_turn: pd.DataFrame, cr: pd.DataFrame) -> dict:
    lpi, turn = sites(points_lpi), sites(points_turn)
    m0, m1 = int(cr["month"].min()), int(cr["month"].max())
    lpi_counts, turn_counts = monthly_counts(lpi, cr, m0, m1), monthly_counts(turn, cr, m0, m1)
    all_xy = np.vstack([lpi[["x", "y"]].to_numpy(), turn[["x", "y"]].to_numpy()])
    all_month = np.concatenate([lpi["month"].to_numpy(), turn["month"].to_numpy()])
    nl = len(lpi)
    # neighbours of each LPI site among all treatment sites (LPI and turn calming), itself excluded
    near = cKDTree(all_xy).query_ball_point(lpi[["x", "y"]].to_numpy(), NEIGHBOUR_M)
    lpi_nb_all = [all_month[[j for j in n if j != i]] for i, n in enumerate(near)]
    near_lpi = cKDTree(lpi[["x", "y"]].to_numpy()).query_ball_point(lpi[["x", "y"]].to_numpy(), NEIGHBOUR_M)
    lpi_nb = [lpi["month"].to_numpy()[[j for j in n if j != i]] for i, n in enumerate(near_lpi)]

    # citywide trend (comparison group b): crashes more than NEIGHBOUR_M from any LPI or turn-calming site, any date
    dist, _ = cKDTree(all_xy).query(cr[["x", "y"]].to_numpy(), distance_upper_bound=NEIGHBOUR_M)
    away = cr[np.isinf(dist)]
    city = {o: np.bincount(away.loc[away[o], "month"].to_numpy() - m0, minlength=m1 - m0 + 1)[None, :] for o in OUTCOMES}

    def study(counts, site_df, nb, treated_range, comparison, shift=0, length=WINDOW, only=None):
        lo, hi = (_month(d) for d in treated_range)
        real = site_df["month"].to_numpy()
        fake = real - shift
        # windows [m - length, m - 1] and [m + 1, m + length] around the (possibly fake) install month m
        excl = np.array([((n >= r - shift - length) & (n <= r + (length if not shift else -1))).any() for n, r in zip(nb, real)])
        treated = (real >= lo) & (real <= hi) & (fake - length >= m0) & (fake + length <= m1)
        keep = treated & ~excl & (only if only is not None else True)
        idx = np.flatnonzero(keep)
        cohorts = np.unique(fake[idx])
        cohort_of = np.searchsorted(cohorts, fake[idx])
        res = {"treated_in_range": int(treated.sum()), "excluded_neighbour_treatment": int((treated & excl).sum()),
               "_keep": keep}
        if not len(idx):
            return {**res, **{o: None for o in OUTCOMES}, "install_months": None}
        for o in OUTCOMES:
            mat = counts[o]
            before = _window_sum(mat[idx], fake[idx] - length - m0, length)
            after = _window_sum(mat[idx], fake[idx] + 1 - m0, length)
            if comparison == "not_yet_treated":
                elig = _not_yet_treated(cohorts, length, lpi, lpi_nb)
                cm = lpi_counts[o]
                cb = np.stack([_window_sum(cm, np.full(nl, c - length - m0), length) for c in cohorts])
                ca = np.stack([_window_sum(cm, np.full(nl, c + 1 - m0), length) for c in cohorts])
                est = estimate(after, before, cohort_of, ca, cb, elig)
                est["cg_sites_min"] = int(elig.sum(1).min())
                est["cg_sites_median"] = int(np.median(elig.sum(1)))
            else:
                cm = city[o]
                cb = np.array([[_window_sum(cm, np.array([c - length - m0]), length)[0]] for c in cohorts])
                ca = np.array([[_window_sum(cm, np.array([c + 1 - m0]), length)[0]] for c in cohorts])
                est = estimate(after, before, cohort_of, ca, cb, np.ones_like(ca, bool))
            res[o] = est
        res["install_months"] = [_label(int(cohorts.min()) + shift), _label(int(cohorts.max()) + shift)] if len(cohorts) else None
        return res

    main = study(lpi_counts, lpi, lpi_nb_all, LPI_TREATED, "not_yet_treated")
    out = {
        "registered": "validation/BENCH_PREREG.md, T11 (2026-10-31)",
        "data": {"lpi_points": len(points_lpi), "lpi_sites": nl, "turn_points": len(points_turn),
                 "turn_sites": len(turn), "crashes": len(cr), "crash_months": [_label(m0), _label(m1)],
                 "radius_m": RADIUS_M, "merge_m": MERGE_M, "neighbour_m": NEIGHBOUR_M, "window_months": WINDOW},
        "lpi_not_yet_treated": main,
        "lpi_citywide": study(lpi_counts, lpi, lpi_nb_all, LPI_TREATED, "citywide"),
        "lpi_placebo_not_yet_treated": study(lpi_counts, lpi, lpi_nb_all, LPI_TREATED, "not_yet_treated",
                                             shift=PLACEBO_SHIFT, length=PLACEBO_WINDOW),
        "lpi_placebo_citywide": study(lpi_counts, lpi, lpi_nb_all, LPI_TREATED, "citywide",
                                      shift=PLACEBO_SHIFT, length=PLACEBO_WINDOW),
    }
    # added after the registered results were seen: the placebo on exactly the main analysis's sites
    out["lpi_placebo_same_sites_not_yet_treated"] = study(lpi_counts, lpi, lpi_nb_all, LPI_TREATED, "not_yet_treated",
                                                          shift=PLACEBO_SHIFT, length=PLACEBO_WINDOW,
                                                          only=main["_keep"])
    near_t = cKDTree(all_xy).query_ball_point(turn[["x", "y"]].to_numpy(), NEIGHBOUR_M)
    turn_nb = [all_month[[j for j in n if j != nl + i]] for i, n in enumerate(near_t)]
    out["turn_calming_citywide"] = study(turn_counts, turn, turn_nb, TURN_TREATED, "citywide")
    out["turn_calming_placebo_citywide"] = study(turn_counts, turn, turn_nb, TURN_TREATED, "citywide",
                                                 shift=PLACEBO_SHIFT, length=PLACEBO_WINDOW)
    for v in out.values():
        if isinstance(v, dict):
            v.pop("_keep", None)
    return out


def brief_cmf() -> list[dict]:
    """The CMF Clearinghouse records the brief would rank a Leading Pedestrian Interval with, for pedestrian crashes."""
    from . import countermeasures
    cands, _ = countermeasures.candidates(countermeasures.load_cmf(), ("vehicle", "pedestrian"), "crossing",
                                          control="Signalized",
                                          conditions=frozenset(i["condition"] for i in countermeasures.psc_items()
                                                               if i.get("condition")))
    return [{"cmf_id": c.crfid, "cmf": round(c.cmf, 3), "stars": c.stars, "crash_type": c.crash_type,
             "severity": c.severity} for c in cands if c.psc == "Leading Pedestrian Interval"]


def projection(effect: dict, cr: pd.DataFrame, lpi_points: pd.DataFrame, months: int = 60) -> dict:
    """Descriptive, added after T11: the NYC Vision Zero priority intersections with no LPI within 60 m, and the
    pedestrian injury crashes (within 100 m, each counted once, over the last `months` months of records) that the
    effect measured at the city's own installs suggests an LPI would avoid. An LPI needs a signal and a site check."""
    from . import harm
    rows = pd.DataFrame(json.loads((RESULTS_DIR / "bench" / "citywide_nyc.json").read_text())["rows"])
    ixy = _xy(rows["lat"], rows["lon"])
    dist, _ = cKDTree(_xy(lpi_points["lat"], lpi_points["lon"])).query(ixy, distance_upper_bound=60)
    none = np.flatnonzero(~np.isfinite(dist))
    m1 = int(cr["month"].max())
    m0 = m1 - months + 1
    near = cKDTree(cr[["x", "y"]].to_numpy()).query_ball_point(ixy[none], 100)
    idx = np.unique(np.concatenate([np.asarray(n, int) for n in near])) if len(none) else np.zeros(0, int)
    sel = idx[cr["pedestrian"].to_numpy()[idx] & (cr["month"].to_numpy()[idx] >= m0)]
    per_year = len(sel) / (months / 12)
    theta, (lo, hi) = effect["theta"], effect["ci95"]
    avoided = [per_year * (1 - t) for t in (theta, hi, lo)]
    return {"intersections": int(len(rows)), "without_lpi": int(len(none)),
            "without_lpi_plan_gap": int(rows.loc[none, "plan_gap"].fillna(False).sum()),
            "months": [_label(m0), _label(m1)], "pedestrian_injury_crashes": int(len(sel)),
            "per_year": round(per_year, 1), "avoided_per_year": round(avoided[0], 1),
            "avoided_per_year_interval": [round(avoided[1], 1), round(avoided[2], 1)],
            "harm_avoided_usd_per_year": round(avoided[0] * harm.INJURY_CRASH_USD, -5),
            "names": rows.loc[none, "name"].tolist()}


def run() -> dict:
    lpi = _points(LPI, "install_da")
    turn = _points(TURN, "completion")
    cr = crashes()
    out = analyse(lpi, turn, cr)
    out["lpi_gap_projection"] = projection(out["lpi_not_yet_treated"]["pedestrian"], cr, lpi)
    out["brief_cmf"] = brief_cmf()
    nyt = out["lpi_not_yet_treated"]["pedestrian"]
    out["rule_met"] = bool(nyt["ci95"][1] < 1)
    plc = out["lpi_placebo_not_yet_treated"]["pedestrian"]
    out["placebo_flag"] = bool(plc["ci95"][1] < 1 or plc["ci95"][0] > 1)
    out["run_date"] = dt.date.today().isoformat()
    dest = RESULTS_DIR / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "treatments_nyc.json").write_text(json.dumps(out, indent=1, default=float))
    return out


LOCAL = {"nyc": {"Leading Pedestrian Interval": ("lpi_not_yet_treated", "lpi_placebo_same_sites_not_yet_treated")}}


def local_evidence(city: str | None, countermeasure: str) -> dict | None:
    """What NML-Bench T11 measured for this countermeasure at the city's own past installs, if it was tested and the
    registered rule was met (the placebo check included); None otherwise."""
    keys = LOCAL.get(city or "", {}).get(countermeasure)
    p = RESULTS_DIR / "bench" / "treatments_nyc.json"
    if not keys or not p.exists():
        return None
    res = json.loads(p.read_text())
    main, placebo = res[keys[0]]["pedestrian"], res[keys[1]]["pedestrian"]
    if not res.get("rule_met"):
        return None
    lo, hi = (round(100 * (1 - v)) for v in reversed(main["ci95"]))
    return {"theta": main["theta"], "ci95": main["ci95"], "sites": main["sites"], "placebo_theta": placebo["theta"],
            "placebo_ci95": placebo["ci95"], "source": "NML-Bench T11 (validation/BENCH.md)",
            "text": f"pedestrian injury crashes fell {round(-main['change_pct'])}% (95% interval {lo}-{hi}%) at "
                    f"{main['sites']:,} intersections after the city installed it, against sites that got it later; "
                    + ("a placebo date before the install shows no drop." if placebo["ci95"][0] <= 1 <= placebo["ci95"][1]
                       else "but a placebo date before the install also shows a change, so part of it may be bias.")}
