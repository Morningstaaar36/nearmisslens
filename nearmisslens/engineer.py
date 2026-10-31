"""The safety engineer: one agent that takes a city or a corner and returns the case for fixing it.

    screen_city -> root_cause -> test_programs -> choose_fixes -> who_must_act -> draft_request -> finish

Each tool is plain code over public records with a check inside it, and returns its data with a receipt: the
datasets it read, the as-of date, the checks it ran and how long it took. The model (when there is one) only decides
what to look at and how to say it. finish refuses any claim that does not cite a receipt, or whose numbers are not
that receipt's values for the label they sit next to (context.FactCheck), so the agent cannot state anything the
tools did not find.

Two ways to run it:
  plan(query)              deterministic and model-free: the same steps in a fixed order, claims written by code.
                           Used without a key or budget, and for the static site.
  run(query, client)       a function-calling loop on Muse Spark Open; the model chooses the steps and writes the
                           claims, and the tools and the finish gate decide what is true.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import brief, citywide, context, jurisdiction, opendata, rootcause, treatments
from .config import asof

SCALE_ORDER = ("low-cost", "reconstruction")


@dataclass
class Desk:
    """The engineer's working state: receipts and the data behind each, and the dossiers fetched so far."""
    receipts: list[dict] = field(default_factory=list)
    data: dict[str, dict] = field(default_factory=dict)
    dossiers: dict[tuple, dict] = field(default_factory=dict)
    places: set[str] = field(default_factory=set)  # corner names: "East 138 Street" holds no count to check

    def record(self, tool: str, data: dict, sources: list[str], checks: list[str], t0: float, summary: str) -> str:
        rid = f"R{len(self.receipts) + 1}"
        self.receipts.append({"id": rid, "tool": tool, "summary": summary, "asof": asof().isoformat(),
                              "sources": sorted({s for s in sources if s}), "checks": checks,
                              "seconds": round(time.perf_counter() - t0, 2)})
        self.data[rid] = data
        return rid

    def dossier(self, lat: float, lon: float) -> dict:
        key = (round(lat, 6), round(lon, 6))
        if key not in self.dossiers:
            self.dossiers[key] = context.dossier(lat, lon)
        return self.dossiers[key]


# ------------------------------------------------------------------------------------------------- the tools

def screen_city(desk: Desk, city: str, top: int = 10) -> tuple[dict, str]:
    """The city's priority junctions ranked by injury crashes, from its saved plan-gap screen."""
    t0 = time.perf_counter()
    screens = dict(citywide.screened())
    if city not in screens:
        raise ValueError(f"no saved screen for {city!r}; run: nml citywide --city {city}")
    res = screens[city]
    rows = sorted((r for r in res["rows"] if not r.get("error")), key=lambda r: -(r.get("injury_crashes") or 0))
    data = {"city": city, "name": (opendata.city(city) or {}).get("name", city), "summary": res.get("summary", {}),
            "top": rows[:top]}
    srcs = [a.get("source") for a in opendata.adapters_of(city, "crash")] + \
           [a.get("source") for a in citywide.junction_adapters(city)]
    rid = desk.record("screen_city", data, srcs,
                      ["each crash counted once where junction circles overlap (distinct counting)",
                       f"crash records from {rows[0].get('since') if rows else '?'} to the as-of date"],
                      t0, f"{len(rows)} priority junctions screened; worst: {rows[0]['name'] if rows else 'none'}")
    return data, rid


def root_cause(desk: Desk, lat: float, lon: float) -> tuple[dict, str]:
    """What the crashes at the corner have in common, against the city's priority junctions."""
    t0 = time.perf_counter()
    data = rootcause.analyse(lat, lon)
    over = data.get("over_represented") or []
    checks = ["one-sided binomial test against the pooled crashes of the city's priority junctions, Holm-corrected",
              f"needs at least {rootcause.MIN_CRASHES} crashes"]
    if data.get("not_recorded"):
        checks.append("not in this dataset: " + ", ".join(data["not_recorded"]))
    rid = desk.record("root_cause", data, [data.get("source")], checks, t0,
                      ("over-represented: " + ", ".join(t["pattern"] for t in over)) if over
                      else "no pattern stands out against the city's priority junctions")
    return data, rid


def test_programs(desk: Desk, lat: float, lon: float) -> tuple[dict, str]:
    """What the city's own past programs did (the causal gate), and whether this corner already got one that the
    record does not support."""
    t0 = time.perf_counter()
    d = desk.dossier(lat, lon)
    projects = (d.get("plans") or {}).get("projects", [])
    progs = treatments.programs(d.get("city"))
    data = {"city": d.get("city"), "programs": progs, "repeat_risk": treatments.repeat_risk(d.get("city"), projects),
            "projects_here": projects, "in_place": list(brief.in_place(d).values())}
    rid = desk.record("test_programs", data, [p["source"] for p in progs] + [p.get("dataset") for p in projects],
                      ["comparison-group before/after against sites treated later or the citywide trend",
                       "placebo install date 19 months early must show no change", "95% bootstrap interval"],
                      t0, f"{len(progs)} programs tested in this city; {len(data['repeat_risk'])} repeat-risk flags here")
    return data, rid


def choose_fixes(desk: Desk, lat: float, lon: float) -> tuple[dict, str]:
    """Federal Proven Safety Countermeasures the record supports, with crashes avoided and dollars."""
    from .countermeasures import load_cmf
    t0 = time.perf_counter()
    d = desk.dossier(lat, lon)
    fx = brief.fix_options(d, load_cmf())
    data = {"crashes": d.get("crashes"), **fx}
    srcs = [(d.get("crashes") or {}).get("source"), "CMF Clearinghouse (curated, data/cmf_allow.csv)",
            "FHWA Proven Safety Countermeasures", "U.S. DOT BCA Guidance 2026, Table A-1"]
    top = fx["options"][0]["countermeasure"] if fx.get("options") else "none"
    rid = desk.record("choose_fixes", data, srcs,
                      [f"CMF must match the site's control ({fx.get('control')}) and a crash population the record shows",
                       "FHWA-cited CMF, else the median of eligible records; never the largest",
                       "a fix the city's own record contradicts is ranked lower"],
                      t0, f"top fix: {top}; {len(fx.get('not_estimated') or [])} fixes listed without a number")
    return data, rid


def _streets(name: str, d: dict) -> list[str]:
    named = [s.strip() for s in re.split(r"\s*&\s*|\s+and\s+", name.split(",")[0]) if s.strip()]
    return named or [r["name"] for r in (d.get("street") or {}).get("roads", []) if r.get("name")]


def who_must_act(desk: Desk, lat: float, lon: float, name: str) -> tuple[dict, str]:
    """Who owns each road at the corner and who can request the work."""
    t0 = time.perf_counter()
    d = desk.dossier(lat, lon)
    data = jurisdiction.who_must_act(lat, lon, _streets(name, d), d.get("street"))
    srcs = [r["basis"].get("dataset") for r in data["owners"] + data["requesters"]]
    rid = desk.record("who_must_act", data, srcs,
                      ["no party without the dataset row behind it", "inferred owners are marked as inferred"],
                      t0, data["summary"])
    return data, rid


def draft_request(desk: Desk, lat: float, lon: float, name: str, who: dict, client=None,
                  audience: str = "agency") -> tuple[dict, str]:
    """The request letter: to the road owners, copying the offices that can push for it (agency), or to the council
    member (resident). Facts only without a client; with one, the letter is drafted and number-checked."""
    from . import letter
    t0 = time.perf_counter()
    d = desk.dossier(lat, lon)
    from .countermeasures import load_cmf
    b = {"junction": name, "dossier": d, "fixes": brief.fix_options(d, load_cmf())}
    out = letter.draft(client, b, who=who, audience=audience) if client is not None else \
        {"letter": None, "facts": letter.facts(b, who=who, audience=audience)}
    rid = desk.record("draft_request", out, letter.sources(b, out["facts"]),
                      ["every number in the letter must be the record's value for the label next to it"]
                      + (["drafted by the model, checked before it is shown"] if client is not None else []),
                      t0, f"letter to {out['facts']['to']}" + ("" if out.get("letter") else " (facts only)"))
    return out, rid


# ------------------------------------------------------------------------------------------------- the finish gate

# words the record cannot support: police factors are not proven causes, and an effect not shown is not shown absent
OVERCLAIM = re.compile(r"\b(caused|causes|cause of|failed|fails|failure|proves?|proved|doesn't work|does not work)\b", re.I)


QUOTED = re.compile(r"\u201c[^\u201d]*\u201d|\"[^\"]*\"")  # the record's own words, e.g. "failure to yield"


def wording(text: str) -> list[str]:
    return [f"'{m.group(0)}' overstates the record: say 'have in common' for patterns and 'not shown' for programs"
            for m in OVERCLAIM.finditer(QUOTED.sub("", text or ""))]


def strip_places(text: str, desk: Desk) -> str:
    """The text with the corner's name (and each of its streets) taken out, longest first."""
    names = {n for p in desk.places for n in [p, *re.split(r"\s*&\s*", p)] if n}
    for n in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(n), "the place", text, flags=re.I)
    return text


def check_summary(summary: str, desk: Desk) -> list[str]:
    """The free-text summary: its numbers must be in some receipt, under the right labels, and its wording plain."""
    s = strip_places(summary or "", desk)
    return [f"summary: {e}" for e in context.FactCheck(desk.data).text(s) + wording(s)]


def recheck(report: dict) -> dict:
    """A saved report's claims checked again with the current checker (receipts rebuilt from its findings)."""
    desk = Desk(receipts=report["receipts"],
                data={r["id"]: report["findings"][r["tool"]] for r in report["receipts"] if r["tool"] in report["findings"]})
    desk.places.add(report["junction"]["name"].split(",")[0])
    errors = check_claims(report["claims"], desk, REQUIRED)
    if report.get("summary"):
        errors += check_summary(report["summary"], desk)
    return {**report, "claim_errors": errors}


def check_claims(claims: list[dict], desk: Desk, required: tuple[str, ...] = ()) -> list[str]:
    """Every claim cites a receipt and its numbers are that receipt's values for their labels; every required tool
    has at least one claim citing it; no claim overstates what the record can show."""
    errors, cited = [], set()
    for k, c in enumerate(claims, 1):
        c = {**c, "text": strip_places(c.get("text", ""), desk)}
        errors += [f"claim {k}: {e}" for e in wording(c["text"])]
        rid = c.get("receipt")
        if rid not in desk.data:
            errors.append(f"claim {k} cites no receipt (got {rid!r})")
            continue
        cited.add(next(r["tool"] for r in desk.receipts if r["id"] == rid))
        errors += [f"claim {k}: {e}" for e in context.FactCheck(desk.data[rid]).text(c.get("text", ""))]
    errors += [f"no claim cites {t}" for t in required if t not in cited]
    return errors


def _usd(v: float) -> str:
    return f"${v / 1e6:.1f} million" if v >= 1e6 else f"${v:,.0f}"


def _basis(owner: dict) -> str:
    source = (owner.get("basis") or {}).get("dataset") or "the record"
    source = source.split(" (")[0]
    return {"recorded": f"owner recorded in {source}",
            "inferred": f"not listed in {source}, so a city street",
            "designation only": "signed route in OpenStreetMap; owner not confirmed"}.get(owner["confidence"], source)


def claims_for(name: str, rec: dict[str, tuple[dict, str]]) -> list[dict]:
    """The deterministic report: one sentence per finding, each with its receipt."""
    out = []
    fx, rf = rec["choose_fixes"]
    cr = fx.get("crashes") or {}
    if cr and "error" not in cr:
        killed = sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed"))
        out.append({"text": f"{name} had {cr.get('injury_crashes', 0)} injury crashes in police records since "
                            f"{cr.get('since')}: {cr.get('pedestrian_injured', 0)} pedestrians injured, "
                            f"{cr.get('cyclist_injured', 0)} cyclists injured and {killed} people killed.",
                    "receipt": rf})
        if fx.get("harm"):
            out.append({"text": f"At the U.S. DOT's values that harm costs about {_usd(fx['harm']['usd_per_year'])} "
                                "a year.", "receipt": rf})
    rc, rr = rec["root_cause"]
    over = rc.get("over_represented") or []
    if over:
        out += [{"text": f"{treatments.pct(100 * t['share'])}% of crashes here {t['phrase']}, against "
                         f"{treatments.pct(100 * t['city_share'])}% at the city's priority junctions.", "receipt": rr}
                for t in over[:3]]
    elif rc.get("crashes") is not None:
        out.append({"text": "No crash pattern here stands out against the city's priority junctions"
                            + ("" if rc.get("enough_crashes") else " (too few crashes to test)") + ".", "receipt": rr})
    pg, rp = rec["test_programs"]
    out += [{"text": f["text"], "receipt": rp} for f in pg["repeat_risk"]]
    seen = set()
    for p in pg["programs"]:
        if p["label"] in seen:
            continue
        seen.add(p["label"])
        out.append({"text": f"The city's {p['label']}: {p['status']} ({p['text']}).", "receipt": rp})
    for o in [o for o in fx.get("options", []) if o.get("scale") == "low-cost"][:2]:
        out.append({"text": f"{o['countermeasure']} would avoid about {o['expected_crashes_avoided_per_year']} "
                            f"crashes a year (CMF {o['cmf_id']}, {o['chosen_by']}), worth "
                            f"{_usd(o['harm_avoided_usd_per_year'])} a year"
                            + (f"; check on site: {o['verify_on_site']}" if o.get("verify_on_site") else "") + ".",
                    "receipt": rf})
    wh, rw = rec["who_must_act"]
    for r in wh["owners"]:
        out.append({"text": f"{r['party'][0].upper() + r['party'][1:]} is responsible for {', '.join(r['roads'])} "
                            f"({_basis(r)}).", "receipt": rw})
    if wh["requesters"]:
        out.append({"text": "Who can push for it: " + "; ".join(r["party"] for r in wh["requesters"]) + ".",
                    "receipt": rw})
    lt, rl = rec["draft_request"]
    to = [o.get("party") or o.get("office") for o in lt["facts"]["addressed_to"]]
    out.append({"text": f"A request letter to {' and '.join(to)} is " + ("drafted and checked." if lt.get("letter")
                                                                          else "ready to draft from these facts."),
                "receipt": rl})
    return out


REQUIRED = ("root_cause", "test_programs", "choose_fixes", "who_must_act")


def _report(query: str, name: str, lat: float, lon: float, desk: Desk, claims: list[dict], t0: float, mode: str,
            extra: dict | None = None) -> dict:
    errors = check_claims(claims, desk, REQUIRED)
    if (extra or {}).get("summary"):
        errors += check_summary(extra["summary"], desk)
    return {"query": query, "junction": {"name": name, "lat": lat, "lon": lon}, "asof": asof().isoformat(),
            "mode": mode, "claims": claims, "claim_errors": errors, "receipts": desk.receipts,
            "findings": {r["tool"]: desk.data[r["id"]] for r in desk.receipts},
            "seconds": round(time.perf_counter() - t0, 2), **(extra or {})}


def _target(query: str, desk: Desk) -> tuple[str, float, float, dict | None]:
    """A city id screens the city and takes its worst corner; anything else is an address."""
    if query in citywide.cities():
        data, rid = screen_city(desk, query, 10)
        if not data["top"]:
            raise ValueError(f"the {query} screen has no junctions")
        j = data["top"][0]
        return f"{j['name']}, {data['name']}", j["lat"], j["lon"], {"screen": rid}
    lat, lon, name = brief.geocode(query)
    return name, lat, lon, None


def plan(query: str, client=None, letter_client=None) -> dict:
    """The deterministic engineer: every tool once, in order, and claims written by code."""
    t0, desk = time.perf_counter(), Desk()
    name, lat, lon, extra = _target(query, desk)
    return investigate(desk, query, name, lat, lon, t0, extra, letter_client)


def investigate(desk: Desk, query: str, name: str, lat: float, lon: float, t0: float | None = None,
                extra: dict | None = None, letter_client=None) -> dict:
    """The five corner tools in order on a known point, and the claims written by code."""
    t0 = t0 if t0 is not None else time.perf_counter()
    desk.places.add(name.split(",")[0])
    rec = {"root_cause": root_cause(desk, lat, lon), "test_programs": test_programs(desk, lat, lon),
           "choose_fixes": choose_fixes(desk, lat, lon)}
    rec["who_must_act"] = who_must_act(desk, lat, lon, name)
    rec["draft_request"] = draft_request(desk, lat, lon, name, rec["who_must_act"][0], letter_client)
    return _report(query, name, lat, lon, desk, claims_for(name.split(",")[0], rec), t0, "deterministic", extra)


def slug(name: str) -> str:
    return re.sub(r"_+", "_", "".join(ch if ch.isalnum() else "_" for ch in name.split(",")[0].lower())).strip("_")[:60]


def precompute(city: str, top: int | None = None, letters: int = 0, letter_client=None, out_dir=None,
               workers: int = 1, saved_only: bool = False) -> list[dict]:
    """The deterministic report for every screened corner of a city (worst first), for the static site; the first
    `letters` corners also get a drafted, checked letter. Saved reports are reused. workers > 1 builds corners in
    parallel (keep it small: OpenStreetMap's Overpass allows a few requests at a time). Returns the index rows."""
    from concurrent.futures import ThreadPoolExecutor
    from .config import SETTINGS
    out_dir = out_dir or SETTINGS.runs_dir / "engineer" / city
    out_dir.mkdir(parents=True, exist_ok=True)
    data, _ = screen_city(Desk(), city, top or 10_000)

    def one(k: int, j: dict) -> dict | None:
        path = out_dir / f"{slug(j['name'])}.json"
        if path.exists():
            rep = json.loads(path.read_text())
            if k >= letters or rep["findings"]["draft_request"].get("letter"):
                return rep
        if saved_only:
            return None
        try:
            rep = investigate(Desk(), j["name"], f"{j['name']}, {data['name']}", j["lat"], j["lon"],
                              letter_client=letter_client if k < letters else None)
        except Exception as e:  # one corner's failure is recorded, not fatal
            print(f"  {j['name']}: {type(e).__name__}: {e}", flush=True)
            return None
        path.write_text(json.dumps(rep, indent=0, default=str))
        return rep

    with ThreadPoolExecutor(max(1, workers)) as pool:
        reports = list(pool.map(lambda kj: one(*kj), enumerate(data["top"])))
    index = []
    for k, (j, rep) in enumerate(zip(data["top"], reports)):
        if rep is None:
            continue
        index.append({"slug": slug(j["name"]), "name": j["name"], "lat": j["lat"], "lon": j["lon"], "rank": k + 1,
                      "injury_crashes": j.get("injury_crashes"), "plan_gap": j.get("plan_gap"),
                      "claim_errors": len(rep["claim_errors"]),
                      "letter": bool(rep["findings"]["draft_request"].get("letter"))})
    return index


# ------------------------------------------------------------------------------------------------- agent mode

INSTRUCTIONS = (
    "You are a city traffic-safety engineer's assistant. Given a city or a street corner, find out: which corner "
    "is worst (screen_city, for a city), what its crashes have in common (root_cause), what the city's own past "
    "programs did and whether this corner already got one that did not show an effect (test_programs), which fixes "
    "the record supports and what they are worth (choose_fixes), who must act (who_must_act), then draft the request "
    "(draft_request). Every tool returns a receipt id. Finish with a short summary and a list of claims, each citing "
    "the receipt it rests on, using only that receipt's numbers next to the right words. Say 'have in common', never "
    "'caused'; say 'not shown', never 'failed'. If finish is refused, fix the claims it names.")


def _screen_and_name(desk: Desk, city: str, top: int) -> tuple[dict, str]:
    data, rid = screen_city(desk, city, top)
    desk.places.update(j["name"] for j in data["top"])
    return data, rid


def _compact(data: dict, limit: int = 6000) -> str:
    text = json.dumps(data, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(truncated)"


def run(query: str, client, model: str = "muse-spark-open", letter_client=None, budget_usd: float = 0.10) -> dict:
    """The agent engineer: the model picks the steps and writes the claims; finish is the gate."""
    from .agent import Tool, run_agent
    from .panel import _obj
    t0, desk = time.perf_counter(), Desk()
    if hasattr(client, "force_finish_after"):  # seven tools come before finish here
        client.force_finish_after = max(client.force_finish_after, 12)
    final: dict = {}
    names: dict[tuple, str] = {}
    num, txt = {"type": "number"}, {"type": "string"}

    def wrap(fn):
        def call(**kw):
            try:
                data, rid = fn(**kw)
            except (ValueError, KeyError) as e:
                return {"error": str(e)}
            return {"receipt": rid, "data": json.loads(_compact(data)) if len(json.dumps(data, default=str)) <= 6000
                    else _compact(data)}
        return call

    def locate(address: str):
        lat, lon, name = brief.geocode(address)
        names[(round(lat, 6), round(lon, 6))] = name
        desk.places.update({name.split(",")[0], address.split(",")[0]})
        return {"lat": lat, "lon": lon, "name": name}

    def finish(summary: str, claims: list[dict]):
        errors = check_claims(claims, desk, REQUIRED) + check_summary(summary, desk)
        if errors:
            return {"error": "refused by the claim checker", "errors": errors[:12]}
        final.update(summary=summary, claims=claims)
        return {"ok": True}

    claim = {"type": "array", "items": _obj({"text": txt, "receipt": txt}, ["text", "receipt"])}
    tools = [
        Tool("screen_city", "Rank a city's priority junctions by injury crashes.",
             _obj({"city": {"type": "string", "enum": citywide.cities()}, "top": {"type": "integer"}}, ["city", "top"]),
             wrap(lambda city, top: _screen_and_name(desk, city, min(int(top), 25)))),
        Tool("locate", "Coordinates for a street corner address.", _obj({"address": txt}, ["address"]), locate),
        Tool("root_cause", "What the corner's crashes have in common.", _obj({"lat": num, "lon": num}, ["lat", "lon"]),
             wrap(lambda lat, lon: root_cause(desk, lat, lon))),
        Tool("test_programs", "The city's own past programs and repeat risk here.",
             _obj({"lat": num, "lon": num}, ["lat", "lon"]), wrap(lambda lat, lon: test_programs(desk, lat, lon))),
        Tool("choose_fixes", "Fixes the record supports, priced.", _obj({"lat": num, "lon": num}, ["lat", "lon"]),
             wrap(lambda lat, lon: choose_fixes(desk, lat, lon))),
        Tool("who_must_act", "Road owners and offices that can request the work.",
             _obj({"lat": num, "lon": num, "name": txt}, ["lat", "lon", "name"]),
             wrap(lambda lat, lon, name: (desk.places.add(name.split(",")[0]), who_must_act(desk, lat, lon, name))[1])),
        Tool("draft_request", "The request letter to the road owners.",
             _obj({"lat": num, "lon": num, "name": txt}, ["lat", "lon", "name"]),
             wrap(lambda lat, lon, name: draft_request(desk, lat, lon, name, jurisdiction.who_must_act(
                 lat, lon, _streets(name, desk.dossier(lat, lon)), desk.dossier(lat, lon).get("street")),
                 letter_client))),
        Tool("finish", "Submit the summary and the claims, each citing a receipt.",
             _obj({"summary": txt, "claims": claim}, ["summary", "claims"]), finish),
    ]
    r = run_agent(client, model, INSTRUCTIONS, f"Task: {query}", tools, 16, budget_usd, effort="low",
                  tag=f"engineer {query[:40]}", escalate_after=3)
    j = next((rec for rec in reversed(desk.receipts) if rec["tool"] in ("choose_fixes", "root_cause")), None)
    d = next(iter(desk.dossiers.items()), None)
    lat, lon = d[0] if d else (None, None)
    name = names.get(d[0], f"{lat}, {lon}") if d else query
    rep = _report(query, name, lat, lon, desk, final.get("claims", []), t0, "agent",
                  {"summary": final.get("summary"), "stopped": r.stopped, "usd": round(r.usd, 5), "turns": r.turns,
                   "tool_calls": [s.tool for s in r.steps] if hasattr(r, "steps") else None})
    rep["finished"] = bool(final) and j is not None
    return rep


def text(report: dict) -> str:
    """The report as plain text for the terminal."""
    lines = [f"{report['junction']['name']}  (records as of {report['asof']}, {report['seconds']} s, "
             f"{report['mode']})", ""]
    for c in report["claims"]:
        lines.append(f"- {c['text']}  [{c['receipt']}]")
    lines += ["", "Receipts:"]
    for r in report["receipts"]:
        lines.append(f"  {r['id']} {r['tool']} ({r['seconds']} s): {r['summary']}")
        lines += [f"      source: {s}" for s in r["sources"][:4]]
        lines += [f"      check: {c}" for c in r["checks"]]
    if report["claim_errors"]:
        lines += ["", "Refused claims:"] + [f"  {e}" for e in report["claim_errors"]]
    return "\n".join(lines)
