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
from .config import ROOT, SETTINGS, since

SPEC = json.loads((ROOT / "validation" / "experiments" / "T15.json").read_text())
EMPTY = rootcause.EMPTY | {"not applicable", "unspecified", "other*", "none"}
BATCH = 120


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


def build(city: str | None = None, top: int | None = None) -> dict:
    """Every crash within the registered radius of the city's screened corners over the 5 years to the as-of date,
    with its features, and each corner's crash ids. Cached under the data directory."""
    city = city or SPEC["city"]
    path = SETTINGS.data_dir / "miner" / f"{city}_{since(5).isoformat()}.json.gz"
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    crash_a = opendata.adapters_of(city, "crash")[0]
    details = opendata.adapters_of(city, "crash_detail")
    rows = sorted(dict(citywide.screened())[city]["rows"], key=lambda r: -(r.get("injury_crashes") or 0))
    corners, crashes = [], {}
    for k, j in enumerate(rows[:top] if top else rows):
        ids = []
        for r in opendata.rows_near(crash_a, j["lat"], j["lon"], SPEC["radius_m"], since(5)):
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
    ds = {"city": city, "since": since(5).isoformat(), "split": SPEC["split"], "corners": corners, "crashes": crashes,
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
    "Use describe and query_crashes to explore this corner's crashes (earlier years only), then use test_pattern on the "
    "mechanisms you think are real and specific: combinations that say what happened (for example a turning maneuver "
    "together with what the pedestrian was doing). Every test you run counts against you in a correction for multiple "
    "testing, and you have at most 12, so test only what you believe. Then call finish with the patterns you stand behind "
    "and one plain sentence each saying what these crashes have in common (never 'caused'). Your patterns will be checked "
    "on later years you cannot see.")


def agent_arm(ds: dict, pool: Pool, corner: dict, client, blind_id: str, max_tests: int = 12,
              budget_usd: float = 0.3) -> dict:
    from .agent import Tool, run_agent
    from .panel import _obj
    sub = period(ds, corner["ids"], False)
    tested: list[list[dict]] = []
    final: dict = {}
    fields = [f for f in SPEC["fields"]]
    cond = {"type": "array", "items": _obj({"field": {"type": "string", "enum": fields}, "value": {"type": "string"}},
                                           ["field", "value"]), "minItems": 1, "maxItems": 3}

    def top_values(ids: list[str], field: str, n: int = 8) -> list[dict]:
        c = Counter(v for i in ids for v in ds["crashes"][i]["f"].get(field, []))
        return [{"value": v, "crashes": k, "share": round(k / max(len(ids), 1), 3),
                 "city_share": round(pool.share([{"field": field, "value": v}], False), 3)} for v, k in c.most_common(n)]

    def describe() -> dict:
        return {"corner": blind_id, "crashes_in_earlier_years": len(sub),
                "fields": {f: top_values(sub, f) for f in fields}}

    def query_crashes(where: list[dict], group_by: str) -> dict:
        ids = [i for i in sub if matches(ds["crashes"][i]["f"], where)]
        return {"matching": len(ids), "of": len(sub), "by": top_values(ids, group_by, 10)}

    def test_pattern(pattern: list[dict], why: str) -> dict:
        if len(tested) >= max_tests:
            return {"error": f"you have used all {max_tests} tests; call finish"}
        tested.append(pattern)
        r = test(ds, pool, corner["ids"], pattern, False)
        return {**r, "tests_used": len(tested), "tests_left": max_tests - len(tested)}

    def finish(findings: list[dict]) -> dict:
        done = {key(p) for p in tested}
        bad = [f"pattern {key(f['pattern'])} was never tested" for f in findings if key(f["pattern"]) not in done]
        bad += [e for f in findings for e in engineer.wording(f.get("mechanism", ""))]
        if bad:
            return {"error": "refused", "errors": bad}
        final["findings"] = findings
        return {"ok": True}

    finding = _obj({"pattern": cond, "mechanism": {"type": "string"}}, ["pattern", "mechanism"])
    tools = [Tool("describe", "This corner's earlier-year crashes: count and top values per field, with city shares.",
                  _obj({}, []), describe),
             Tool("query_crashes", "Among earlier-year crashes matching all conditions, counts by another field.",
                  _obj({"where": {**cond, "minItems": 0}, "group_by": {"type": "string", "enum": fields}},
                       ["where", "group_by"]), query_crashes),
             Tool("test_pattern", "Test one pattern on earlier years (counts toward the correction).",
                  _obj({"pattern": cond, "why": {"type": "string"}}, ["pattern", "why"]), test_pattern),
             Tool("finish", "Report the tested patterns you stand behind.",
                  _obj({"findings": {"type": "array", "items": finding}}, ["findings"]), finish)]
    if hasattr(client, "force_finish_after"):
        client.force_finish_after = max(client.force_finish_after, 16)
    run = run_agent(client, "muse-spark-open", INSTRUCTIONS, f"Corner {blind_id}.", tools, 20, budget_usd,
                    effort="low", tag=f"miner {blind_id}", escalate_after=3)
    reported = [f["pattern"] for f in final.get("findings", [])]
    out = score_arm(ds, pool, corner["ids"], tested, reported)
    texts = {key(f["pattern"]): f["mechanism"] for f in final.get("findings", [])}
    for c in out["confirmed"]:
        c["mechanism"] = texts.get(c["pattern"])
    return {**out, "usd": round(run.usd, 5), "turns": run.turns, "stopped": run.stopped, "finished": bool(final)}


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
