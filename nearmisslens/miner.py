"""Falsification-gated discovery (NML-Bench T15): an agent may explore any crash mechanism it likes, but may only report
what survives a test on later years it never saw.

Each crash near a screened corner gets features from three public tables joined on the collision id: the crash record
(who was hurt, time of day, vehicle kinds, recorded factors), the vehicle table (what each vehicle was doing, its
direction, where it was hit) and the person table (what a pedestrian or cyclist was doing, and where). A pattern is one to
three field=value conditions. Its test is a one-sided binomial: the corner's share of crashes matching it against the
pooled share at all screened corners in the same period.

The years are split at a registered date (validation/experiments/T15.json). Every arm explores before the split only;
the agent's tools cannot read later crashes. Holm's correction runs over every pattern an arm tested, not only those it
reports. The patterns that pass are tested once on the sealed years, by code, after the arm has finished. Null corners
(the same number of crashes drawn at random from all corners) measure how often each arm reports a mechanism that is not
there.

Arms: the agent (Muse Spark Open), the grid (every 1- and 2-condition pattern) and greedy (the 10 patterns with the
largest excess), the last two with no model."""
from __future__ import annotations

import gzip
import itertools
import json
import random
import re
from collections import Counter
from pathlib import Path

from scipy.stats import binomtest

from . import citywide, context, engineer, opendata, rootcause
from .config import ASOF_FILE, ROOT, SETTINGS
from .config import MODELS

SPEC = json.loads((ROOT / "validation" / "experiments" / "T15.json").read_text())
EMPTY = rootcause.EMPTY | {"not applicable", "unspecified", "other*", "none"}
BATCH = 120


def window_start(years: int = 5):
    """The start of the experiment's window: always the pinned as-of date (validation/ASOF), so results and the
    dataset do not move with today's date or the environment."""
    import datetime as dt
    a = dt.date.fromisoformat(ASOF_FILE.read_text().strip())
    return a.replace(year=a.year - years) if not (a.month == 2 and a.day == 29) else a.replace(year=a.year - years, day=28)


def _norm(v) -> str | None:
    s = re.sub(r"\s+", " ", str(v or "")).strip().lower()
    return None if not s or s in EMPTY else s


# ------------------------------------------------------------------------------------------------- features

def crash_features(row: dict, a: dict) -> dict[str, set[str]]:
    """Fields from the crash record itself."""
    f: dict[str, set[str]] = {}
    inj, kil = a.get("injured", {}), a.get("killed", {})
    ped = rootcause._num(row, inj.get("pedestrian", []) + kil.get("pedestrian", []))
    cyc = rootcause._num(row, inj.get("cyclist", []) + kil.get("cyclist", []))
    hurt = sum(rootcause._num(row, fs) for m in (inj, kil) for fs in m.values())
    f["outcome"] = {"pedestrian hurt" if ped else "cyclist hurt" if cyc else "only people in vehicles hurt" if hurt
                    else "no one hurt"}
    h = rootcause._hour(row.get(a.get("time_field") or ""))
    if h is not None:
        f["time"] = {"night (7 pm to 6 am)" if h >= 19 or h < 6 else "daytime"} | (
            {"rush hours"} if 7 <= h < 10 or 16 <= h < 19 else set())
    kinds = " ".join(str(row.get(x) or "").lower() for x in a.get("vehicle_fields", []))
    f["vehicle_kind"] = {g for g, pat in (a.get("vehicle_groups") or {}).items() if re.search(pat, kinds)}
    f["factor"] = {v for x in a.get("factor_fields", []) if (v := _norm(row.get(x)))}
    return {k: v for k, v in f.items() if v}


def detail_features(vehicles: list[dict], persons: list[dict], vroles: dict, proles: dict) -> dict[str, set[str]]:
    """Fields from the vehicle and person tables (a crash has the value if any of its vehicles or people has it). The
    adapters' "roles" map each feature to the dataset's own column, so another city's tables plug in by registry."""
    f: dict[str, set[str]] = {"pre_crash": set(), "maneuver": set(), "point_of_impact": set(), "ped_action": set(),
                              "ped_location": set()}
    col = lambda roles, r, name: _norm(r.get(roles[name])) if roles.get(name) else None
    for v in vehicles:
        pre, d = col(vroles, v, "pre_crash"), col(vroles, v, "direction")
        if pre:
            f["pre_crash"].add(pre)
            if d:
                f["maneuver"].add(f"{pre}, heading {d}")
        if (p := col(vroles, v, "point_of_impact")):
            f["point_of_impact"].add(p)
    for p in persons:
        for name in ("ped_action", "ped_location"):
            if (x := col(proles, p, name)):
                f[name].add(x)
    return {k: v for k, v in f.items() if v}


# ------------------------------------------------------------------------------------------------- the dataset

def _details(a: dict, ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    want = list((a.get("roles") or {}).values()) + [a["join_field"]] + list(a.get("filter") or {})
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        where = f"{a['join_field']} in (" + ",".join(f"'{c}'" for c in chunk) + ")"
        for k, vals in (a.get("filter") or {}).items():
            where += f" AND {k} in (" + ",".join(f"'{v}'" for v in vals) + ")"
        js, _ = context.fetch(a["endpoint"], {"$where": where, "$select": ",".join(dict.fromkeys(want)), "$limit": 5000})
        for r in js if isinstance(js, list) else []:
            out.setdefault(str(r.get(a["join_field"])), []).append(r)
    return out


@__import__("functools").lru_cache(maxsize=2)
def _load(path: str) -> dict:
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def build(city: str | None = None, top: int | None = None) -> dict:
    """Every crash within the registered radius of the city's screened corners over the 5 years to the as-of date,
    with its features, and each corner's crash ids. Cached under the data directory."""
    city = city or SPEC["city"]
    path = SETTINGS.data_dir / "miner" / f"{city}_{window_start(5).isoformat()}.json.gz"
    if path.exists():
        return _load(str(path))
    crash_a = opendata.adapters_of(city, "crash")[0]
    details = opendata.adapters_of(city, "crash_detail")
    rows = sorted(dict(citywide.screened())[city]["rows"], key=lambda r: -(r.get("injury_crashes") or 0))
    corners, crashes = [], {}
    for k, j in enumerate(rows[:top] if top else rows):
        ids = []
        for r in opendata.rows_near(crash_a, j["lat"], j["lon"], SPEC["radius_m"], window_start(5)):
            cid = str(r.get(crash_a["id_field"]))
            date = str(r.get(crash_a["date_field"]) or "")[:10]
            if not cid or not date:
                continue
            ids.append(cid)
            crashes.setdefault(cid, {"date": date, "f": {k2: sorted(v) for k2, v in crash_features(r, crash_a).items()}})
        corners.append({"slug": engineer.slug(j["name"]), "name": j["name"], "rank": k + 1, "ids": sorted(set(ids))})
    all_ids = sorted(crashes)
    found = {a["level"]: _details(a, all_ids) for a in details}
    roles = {a["level"]: a.get("roles") or {} for a in details}
    for cid, c in crashes.items():
        extra = detail_features(found.get("vehicle", {}).get(cid, []), found.get("person", {}).get(cid, []),
                                roles.get("vehicle", {}), roles.get("person", {}))
        c["f"].update({k: sorted(v) for k, v in extra.items()})
    ds = {"city": city, "since": window_start(5).isoformat(), "split": SPEC["split"], "corners": corners, "crashes": crashes,
          "coverage": {lvl: round(sum(cid in m for cid in all_ids) / max(len(all_ids), 1), 3) for lvl, m in found.items()},
          "sources": [crash_a["source"]] + [a["source"] for a in details]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(ds).encode()))
    return ds


# ------------------------------------------------------------------------------------------------- statistics

def period(ds: dict, ids: list[str], sealed: bool) -> list[str]:
    return [i for i in ids if (ds["crashes"][i]["date"] >= ds["split"]) == sealed]


def matches(feat: dict, pattern: list[dict]) -> bool:
    return all(c["value"] in feat.get(c["field"], ()) for c in pattern)


def key(pattern: list[dict]) -> str:
    return " AND ".join(f"{c['field']}={c['value']}" for c in sorted(pattern, key=lambda c: (c["field"], c["value"])))


class Pool:
    """The pooled shares at all screened corners, per period (each crash counted once)."""

    def __init__(self, ds: dict):
        ids = sorted({i for c in ds["corners"] for i in c["ids"]})
        self.ds = ds
        self.ids = {False: period(ds, ids, False), True: period(ds, ids, True)}
        self._cache: dict[tuple, float] = {}

    def share(self, pattern: list[dict], sealed: bool) -> float:
        k = (key(pattern), sealed)
        if k not in self._cache:
            ids = self.ids[sealed]
            self._cache[k] = sum(matches(self.ds["crashes"][i]["f"], pattern) for i in ids) / max(len(ids), 1)
        return self._cache[k]


def test(ds: dict, pool: Pool, ids: list[str], pattern: list[dict], sealed: bool) -> dict:
    sub = period(ds, ids, sealed)
    k = sum(matches(ds["crashes"][i]["f"], pattern) for i in sub)
    p0 = pool.share(pattern, sealed)
    p = binomtest(k, len(sub), p0, alternative="greater").pvalue if sub and 0 < p0 < 1 else 1.0
    return {"pattern": key(pattern), "k": k, "n": len(sub), "share": round(k / len(sub), 3) if sub else 0.0,
            "city_share": round(p0, 4), "p": float(p)}


def holm(ps: list[float], alpha: float) -> list[bool]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out, holding = [False] * len(ps), True
    for rank, i in enumerate(order):
        holding = holding and ps[i] < alpha / (len(ps) - rank)
        out[i] = holding
    return out


def score_arm(ds: dict, pool: Pool, ids: list[str], tested: list[list[dict]], reported: list[list[dict]]) -> dict:
    """Holm over everything tested on explore years; the reported patterns that pass are tested once on sealed years."""
    a = SPEC["alpha"]
    ex = [test(ds, pool, ids, p, False) for p in tested]
    passed = {r["pattern"] for r, ok in zip(ex, holm([r["p"] for r in ex], a)) if ok}
    rep = [p for p in reported if key(p) in passed]
    se = [test(ds, pool, ids, p, True) for p in rep]
    conf = [r for r, ok in zip(se, holm([r["p"] for r in se], a)) if ok]
    return {"tested": len(tested), "reported": len(reported), "explore_passed": len(rep),
            "confirmed": [{**r, "explore": next(e for e in ex if e["pattern"] == r["pattern"])} for r in conf]}


# ------------------------------------------------------------------------------------------------- no-model arms

def candidates(ds: dict, pool: Pool, ids: list[str]) -> list[tuple[list[dict], float]]:
    """1- and 2-condition patterns with at least min_matches explore matches at the corner, with their excess."""
    sub = period(ds, ids, False)
    singles = Counter((f, v) for i in sub for f, vs in ds["crashes"][i]["f"].items() if f in SPEC["fields"] for v in vs)
    keep = [fv for fv, n in singles.items() if n >= SPEC["min_matches"]]
    pairs = Counter()
    for i in sub:
        fv = sorted((f, v) for f, vs in ds["crashes"][i]["f"].items() if f in SPEC["fields"] for v in vs
                    if singles[(f, v)] >= SPEC["min_matches"])
        pairs.update((a, b) for a, b in itertools.combinations(fv, 2) if a[0] != b[0])
    pats = [[{"field": f, "value": v}] for f, v in keep] + \
           [[{"field": a[0], "value": a[1]}, {"field": b[0], "value": b[1]}] for (a, b), n in pairs.items()
            if n >= SPEC["min_matches"]]
    n = len(sub)
    return [(p, sum(matches(ds["crashes"][i]["f"], p) for i in sub) - n * pool.share(p, False)) for p in pats]


def grid_arm(ds: dict, pool: Pool, ids: list[str]) -> dict:
    pats = [p for p, _ in candidates(ds, pool, ids)]
    return score_arm(ds, pool, ids, pats, pats)


def greedy_arm(ds: dict, pool: Pool, ids: list[str], k: int = 10) -> dict:
    top = [p for p, _ in sorted(candidates(ds, pool, ids), key=lambda t: -t[1])[:k]]
    return score_arm(ds, pool, ids, top, top)


def null_corners(ds: dict, pool: Pool, real: list[dict], seed: int) -> list[dict]:
    """For each real corner, the same number of crashes per period drawn at random from all corners' crashes."""
    rng = random.Random(seed)
    out = []
    for k, c in enumerate(real):
        ne, ns = len(period(ds, c["ids"], False)), len(period(ds, c["ids"], True))
        ids = rng.sample(pool.ids[False], min(ne, len(pool.ids[False]))) + rng.sample(pool.ids[True], min(ns, len(pool.ids[True])))
        out.append({"slug": f"null_{k + 1:03d}", "name": None, "null": True, "ids": ids})
    return out


# ------------------------------------------------------------------------------------------------- the agent arm

INSTRUCTIONS = (
    "You are a traffic-safety analyst looking for crash mechanisms at one street corner, identified only by an id. "
    "Call describe, then use at most 8 query_crashes calls to explore this corner's crashes (earlier years only; each "
    "result shows the share of all crashes here and in the city for the combination). Then call propose with up to 12 "
    "patterns you believe are real and specific: combinations that say what happened, for example a turning maneuver "
    "together with what the pedestrian was doing, or a vehicle kind with a maneuver. Every pattern you propose is tested "
    "and corrected for multiple testing, so propose only what you believe; then each survivor is checked once on later "
    "years you cannot see. For each pattern give one plain sentence saying what these crashes have in common (never "
    "'caused').")


def agent_arm(ds: dict, pool: Pool, corner: dict, client, blind_id: str, max_props: int = 12,
              max_queries: int = 8, budget_usd: float = 0.3) -> dict:
    """The agent explores, then proposes; code tests every proposal (all count in the correction) and runs the sealed
    check. The agent never sees a test result or a later-year crash."""
    from .agent import Tool, run_agent
    from .panel import _obj
    sub = period(ds, corner["ids"], False)
    final: dict = {}
    fields = list(SPEC["fields"])
    cond = {"type": "array", "items": _obj({"field": {"type": "string", "enum": fields}, "value": {"type": "string"}},
                                           ["field", "value"]), "minItems": 1, "maxItems": 3}
    queries: list = []

    def top_values(ids: list[str], field: str, n: int = 8) -> list[dict]:
        c = Counter(v for i in ids for v in ds["crashes"][i]["f"].get(field, []))
        return [{"value": v, "crashes": k, "share": round(k / max(len(ids), 1), 3),
                 "city_share": round(pool.share([{"field": field, "value": v}], False), 3)} for v, k in c.most_common(n)]

    def describe() -> dict:
        return {"corner": blind_id, "crashes_in_earlier_years": len(sub),
                "fields": {f: top_values(sub, f) for f in fields}}

    def query_crashes(where: list[dict], group_by: str) -> dict:
        if len(queries) >= max_queries:
            return {"error": f"you have used all {max_queries} queries; call propose now"}
        queries.append(where)
        ids = [i for i in sub if matches(ds["crashes"][i]["f"], where)]
        c = Counter(v for i in ids for v in ds["crashes"][i]["f"].get(group_by, []))
        by = [{"value": v, "crashes": k, "share_of_all_crashes": round(k / max(len(sub), 1), 3),
               "city_share_of_all_crashes": round(pool.share(list(where) + [{"field": group_by, "value": v}], False), 3)}
              for v, k in c.most_common(10)]
        return {"matching": len(ids), "of": len(sub), "by": by, "queries_left": max_queries - len(queries)}

    def propose(findings: list[dict] | None = None) -> dict:
        findings = findings or []
        if not findings:
            return {"error": "propose at least one pattern, each with a mechanism sentence"}
        bad = [e for f in findings for e in engineer.wording(f.get("mechanism", ""))]
        bad += [f"pattern {key(f['pattern'])} has a value this corner never shows"
                for f in findings if not any(matches(ds["crashes"][i]["f"], f["pattern"]) for i in sub)]
        if bad:
            return {"error": "refused", "errors": bad[:8]}
        final["findings"] = findings[:max_props]
        return {"ok": True}

    finding = _obj({"pattern": cond, "mechanism": {"type": "string"}}, ["pattern", "mechanism"])
    tools = [Tool("describe", "This corner's earlier-year crashes: count and top values per field, with city shares.",
                  _obj({}, []), describe),
             Tool("query_crashes", "Among earlier-year crashes matching all conditions, counts by another field.",
                  _obj({"where": {**cond, "minItems": 0}, "group_by": {"type": "string", "enum": fields}},
                       ["where", "group_by"]), query_crashes),
             Tool("finish", "Propose up to 12 patterns you believe, each with one plain sentence.",
                  _obj({"findings": {"type": "array", "items": finding, "maxItems": max_props}}, ["findings"]), propose)]
    if hasattr(client, "force_finish_after"):
        client.force_finish_after = max(client.force_finish_after, 2 + max_queries + 2)
    run = run_agent(client, MODELS["open_label"], INSTRUCTIONS, f"Corner {blind_id}.", tools, 16, budget_usd,
                    effort="low", tag=f"miner {blind_id}", escalate_after=3)
    props = [f["pattern"] for f in final.get("findings", [])]
    out = score_arm(ds, pool, corner["ids"], props, props)
    texts = {key(f["pattern"]): f["mechanism"] for f in final.get("findings", [])}
    for c in out["confirmed"]:
        c["mechanism"] = texts.get(c["pattern"])
    return {**out, "usd": round(run.usd, 5), "turns": run.turns, "stopped": run.stopped, "finished": bool(final),
            "queries": len(queries), "proposals": [{"pattern": key(f["pattern"]), "mechanism": f["mechanism"]}
                                                   for f in final.get("findings", [])]}


# ------------------------------------------------------------------------------------------------- T15

def run_t15(arms: tuple[str, ...] = ("grid", "greedy", "agent"), real: int | None = None, nulls: int | None = None,
            client=None, out: Path | None = None) -> dict:
    """Every arm on the top corners and their null twins; results are written after each corner."""
    from .evaluate import RESULTS_DIR
    ds = build(SPEC["city"])
    pool = Pool(ds)
    corners = [c for c in ds["corners"] if len(period(ds, c["ids"], False)) >= SPEC["corners"]["min_explore_crashes"]]
    corners = corners[:real or SPEC["corners"]["top"]]
    twins = null_corners(ds, pool, corners, SPEC["null_corners"]["seed"])[:nulls if nulls is not None else SPEC["null_corners"]["count"]]
    out = out or RESULTS_DIR / "bench" / "experiment_T15.json"
    res = json.loads(out.read_text()) if out.exists() else {"id": "T15", "spec": SPEC, "runs": []}
    done = {(r["arm"], r["corner"]) for r in res["runs"]}
    order = [(c, False) for c in corners] + [(c, True) for c in twins]
    rng = random.Random(SPEC["null_corners"]["seed"])
    blind = {c["slug"]: f"corner-{rng.randrange(10**6):06d}" for c, _ in order}
    for arm in arms:
        for c, is_null in order:
            if (arm, c["slug"]) in done:
                continue
            if arm == "agent":
                if client is None:
                    continue
                r = agent_arm(ds, pool, c, client, blind[c["slug"]])
            else:
                r = (grid_arm if arm == "grid" else greedy_arm)(ds, pool, c["ids"])
            res["runs"].append({"arm": arm, "corner": c["slug"], "null": is_null, **r})
            out.write_text(json.dumps(res, indent=0, default=str))
    res["summary"] = summarise(res["runs"])
    out.write_text(json.dumps(res, indent=0, default=str))
    return res


def summarise(runs: list[dict]) -> dict:
    out = {}
    for arm in sorted({r["arm"] for r in runs}):
        real = [r for r in runs if r["arm"] == arm and not r["null"]]
        null = [r for r in runs if r["arm"] == arm and r["null"]]
        conf = sum(len(r["confirmed"]) for r in real)
        rep = sum(r["reported"] for r in real)
        out[arm] = {"real_corners": len(real), "null_corners": len(null),
                    "confirmed_per_corner": round(conf / max(len(real), 1), 3),
                    "precision": round(conf / rep, 3) if rep else None,
                    "null_false_per_corner": round(sum(len(r["confirmed"]) for r in null) / max(len(null), 1), 3),
                    "tested_per_corner": round(sum(r["tested"] for r in real) / max(len(real), 1), 1),
                    "usd": round(sum(r.get("usd", 0) for r in real + null), 3)}
    return out


# ------------------------------------------------------------------------------------------------- analysis

def _crashes_of(ds: dict, ids: list[str], pattern_key: str) -> set[str]:
    pat = [{"field": c.split("=", 1)[0], "value": c.split("=", 1)[1]} for c in pattern_key.split(" AND ")]
    return {i for i in period(ds, ids, False) if matches(ds["crashes"][i]["f"], pat)}


def _overlap(a: set, b: set) -> float:
    return len(a & b) / max(min(len(a), len(b)), 1)


def distinct(ds: dict, ids: list[str], confirmed: list[dict], min_overlap: float = 0.8) -> list[dict]:
    """Confirmed findings merged when their explore-year crashes overlap by at least min_overlap (largest first)."""
    kept: list[tuple[dict, set]] = []
    for c in sorted(confirmed, key=lambda c: -c["explore"]["k"]):
        s = _crashes_of(ds, ids, c["pattern"])
        if all(_overlap(s, t) < min_overlap for _, t in kept):
            kept.append((c, s))
    return [c for c, _ in kept]


def analyse(res: dict, ds: dict | None = None, boot: int = 2000, seed: int = 15) -> dict:
    """The registered rule (bootstrap over corners), distinct findings, and findings only one arm confirmed."""
    import numpy as np
    ds = ds or build(SPEC["city"])
    ids_of = {c["slug"]: c["ids"] for c in ds["corners"]}
    runs = [r for r in res["runs"] if not r["null"]]
    arms = sorted({r["arm"] for r in runs})
    by = {(r["arm"], r["corner"]): r for r in runs}
    corners = sorted({r["corner"] for r in runs if all((a, r["corner"]) in by for a in arms)})
    out = {"corners_with_every_arm": len(corners), "summary": summarise(res["runs"])}
    count = {a: np.array([len(by[(a, c)]["confirmed"]) for c in corners]) for a in arms}
    dist = {a: [distinct(ds, ids_of[c], by[(a, c)]["confirmed"]) for c in corners] for a in arms}
    out["distinct_per_corner"] = {a: round(float(np.mean([len(d) for d in dist[a]])), 3) if corners else None for a in arms}
    rng = np.random.default_rng(seed)
    if "agent" in arms and corners:
        diffs = {}
        for b in (x for x in arms if x != "agent"):
            for name, a_vals, b_vals in (("count", count["agent"], count[b]),
                                         ("distinct", np.array([len(d) for d in dist["agent"]]),
                                          np.array([len(d) for d in dist[b]]))):
                d = a_vals - b_vals
                bs = [float(np.mean(rng.choice(d, len(d)))) for _ in range(boot)]
                diffs[f"agent_minus_{b}_{name}"] = {"mean": round(float(d.mean()), 3),
                                                    "ci95": [round(float(np.percentile(bs, 2.5)), 3),
                                                             round(float(np.percentile(bs, 97.5)), 3)]}
        out["differences"] = diffs
        null_rate = out["summary"].get("agent", {}).get("null_false_per_corner")
        out["rule_met"] = bool(all(diffs[f"agent_minus_{b}_count"]["ci95"][0] > 0 for b in arms if b != "agent")
                               and null_rate is not None and null_rate <= 0.05)
        only = []  # agent findings no other arm confirmed at that corner (by 80% crash overlap)
        for c, d in zip(corners, dist["agent"]):
            others = [_crashes_of(ds, ids_of[c], f["pattern"]) for b in arms if b != "agent" for f in by[(b, c)]["confirmed"]]
            for f in d:
                s = _crashes_of(ds, ids_of[c], f["pattern"])
                if all(_overlap(s, t) < 0.8 for t in others):
                    only.append({"corner": c, "pattern": f["pattern"], "share": f["share"], "city_share": f["city_share"],
                                 "mechanism": f.get("mechanism")})
        out["agent_only"] = only
        out["agent_only_corners"] = len({x["corner"] for x in only})
    return out


# ------------------------------------------------------------------------------------------------- for the product

WORDS = {"pre_crash": "a vehicle was {v}", "maneuver": "a vehicle was {v}", "point_of_impact": "a vehicle was hit on the {v}",
         "ped_action": "the pedestrian or cyclist was {v}", "ped_location": "the pedestrian or cyclist was at {v}",
         "outcome": "{v}", "time": "it happened in the {v}", "vehicle_kind": "a {v} was involved",
         "factor": "“{v}” was recorded"}


def words(pattern_key: str) -> str:
    """'maneuver=making left turn, heading west AND ped_action=crossing with signal' in plain words."""
    parts = []
    for c in pattern_key.split(" AND "):
        f, v = c.split("=", 1)
        parts.append(WORDS.get(f, f + ": {v}").format(v=v))
    return " and ".join(parts)


def corner_mechanisms(slug: str, res: dict | None = None, ds: dict | None = None) -> list[dict]:
    """The mechanisms confirmed at a corner by any T15 arm, merged by crash overlap, each with who found it, the
    explore and sealed shares, and the agent's sentence when it found it."""
    from .evaluate import RESULTS_DIR
    p = RESULTS_DIR / "bench" / "experiment_T15.json"
    res = res or (json.loads(p.read_text()) if p.exists() else None)
    if not res:
        return []
    rows = [r for r in res["runs"] if r["corner"] == slug and not r["null"]]
    if not rows:
        return []
    ds = ds or build(res.get("spec", SPEC)["city"])
    ids = next((c["ids"] for c in ds["corners"] if c["slug"] == slug), [])
    found = []
    for r in sorted(rows, key=lambda r: r["arm"] != "agent"):  # the agent's wording first, when it found the same thing
        for c in r["confirmed"]:
            s = _crashes_of(ds, ids, c["pattern"])
            hit = next((f for f in found if _overlap(s, f["_s"]) >= 0.8), None)
            if hit:
                hit["found_by"] = sorted(set(hit["found_by"]) | {r["arm"]})
                continue
            found.append({"pattern": c["pattern"], "words": words(c["pattern"]), "found_by": [r["arm"]],
                          "mechanism": c.get("mechanism"),
                          "explore": {k: c["explore"][k] for k in ("k", "n", "share", "city_share")},
                          "sealed": {k: c[k] for k in ("k", "n", "share", "city_share")}, "_s": s})
    for f in found:
        f.pop("_s")
    return sorted(found, key=lambda f: -(f["sealed"]["share"] - f["sealed"]["city_share"]))
