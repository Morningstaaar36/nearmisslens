"""Junction Safety Brief: from an address to a ranked, cited, checked plan for a city engineer.

1. The official record (context.dossier): street layout, police-reported crashes over five years, the city's priority
   designations and its projects.
2. Fix options: every FHWA Proven Safety Countermeasure whose CMF Clearinghouse record targets a crash group the
   record shows (pedestrian, angle/turning, rear-end), with expected crashes avoided per year by the Highway Safety
   Manual's simple method, observed crashes per year x (1 - CMF). This is not the Empirical Bayes method; the brief
   says so.
3. The top option drawn by Muse Image on the city's own aerial photo, with a SAM 3.1 check that it was added.
4. A memo agent (Muse Spark, or Muse Spark Open on Baseten) writes the brief; a checker rejects any number that is not
   in the facts."""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import cv2
import httpx
import numpy as np

from . import context, countermeasures, harm, panel, sam_api
from .agent import Tool, run_agent
from .config import SETTINGS

YEARS = context.YEARS
OVERPASS_SERVERS = (context.OVERPASS, "https://overpass.private.coffee/api/interpreter",
                    "https://maps.mail.ru/osm/tools/overpass/api/interpreter")


def geocode(address: str) -> tuple[float, float, str]:
    """An address, or an intersection written 'Street A & Street B, City': Nominatim finds the area, and for an
    intersection OpenStreetMap gives the node shared by the two streets nearest to it."""
    streets = address.split(",")[0]
    rest = ",".join(address.split(",")[1:])
    first = streets.split("&")[0].strip() if "&" in streets else streets
    js, _ = context.fetch("https://nominatim.openstreetmap.org/search",
                          {"q": f"{first},{rest}", "format": "jsonv2", "limit": 1, "countrycodes": "us"})
    if not js:
        raise ValueError(f"address not found: {address}")
    lat, lon, name = float(js[0]["lat"]), float(js[0]["lon"]), js[0].get("display_name", address)
    if "&" not in streets:
        return lat, lon, name
    a, b = (x.strip() for x in streets.split("&")[:2])
    jb, _ = context.fetch("https://nominatim.openstreetmap.org/search",
                          {"q": f"{b},{rest}", "format": "jsonv2", "limit": 1, "countrycodes": "us"})
    if jb:  # long streets: search around the midpoint of the two streets' anchors, wide enough to reach both
        lat, lon = (lat + float(jb[0]["lat"])) / 2, (lon + float(jb[0]["lon"])) / 2
    q = (f'[out:json][timeout:90];way(around:12000,{lat},{lon})[highway][name~"^{a}$",i]->.a;'
         f'way(around:12000,{lat},{lon})[highway][name~"^{b}$",i]->.b;node(w.a)(w.b);out;')
    res = None
    for server in OVERPASS_SERVERS:  # the public servers fail now and then; try the next one
        try:
            res, _ = context.fetch(server, data={"data": q}, timeout=150)
            break
        except RuntimeError:
            continue
    if res is None:
        raise ValueError("OpenStreetMap servers are unavailable; try again or give coordinates")
    nodes = [(e["lat"], e["lon"]) for e in res.get("elements", []) if e.get("type") == "node"]
    if not nodes:
        raise ValueError(f"no intersection of {a} and {b} found near {name}")
    lat2, lon2 = min(nodes, key=lambda n: (n[0] - lat) ** 2 + (n[1] - lon) ** 2)
    return lat2, lon2, f"{a} & {b}, {rest.strip()}"


def in_place(d: dict) -> dict[str, dict]:
    """Proven Safety Countermeasures the city's records show already installed at the junction, with the year: a
    project adapter whose records are themselves a countermeasure says so in the registry ("countermeasure")."""
    from . import opendata
    out = {}
    for p in (d.get("plans") or {}).get("projects", []):
        name = (opendata.adapter(p.get("dataset") or "") or {}).get("countermeasure")
        if name and (name not in out or (p.get("year") or 0) < (out[name].get("year") or 0)):
            out[name] = {"countermeasure": name, "year": p.get("year"), "dataset": p.get("dataset")}
    return out


def _conditions(d: dict, min_share: float = 0.05) -> frozenset[str]:
    """Countermeasure preconditions the crash record supports: a contributing factor behind at least min_share of
    the crashes."""
    from . import opendata
    cr = d.get("crashes") or {}
    total = max(cr.get("crashes", 0), 1)
    # each crash dataset words its contributing factors differently; its adapter maps them to conditions
    mapping = (opendata.adapter(cr.get("adapter") or "") or {}).get("factor_conditions", {})
    conds = set()
    for f, n in (cr.get("factor_counts") or {}).items():
        c = mapping.get(str(f).lower())
        if c and n / total >= min_share:
            conds.add(c)
    if "a turning movement" in conds:
        conds.add("a left-turn movement")
    # conditions some cities record per crash (opendata light and surface fields)
    if (cr.get("dark_share") or 0) >= 0.25:
        conds.add("nighttime")
    if (cr.get("wet_share") or 0) >= 0.15:
        conds.add("wet or low-friction pavement")
    return frozenset(conds)


def fix_options(d: dict, cmf) -> dict:
    """Countermeasures for the crash groups in the record, ranked by expected crashes avoided per year."""
    cr = d.get("crashes") or {}
    if not cr or "error" in cr:
        return {"options": [], "rejected": [], "note": "no crash record available for this location"}
    g = cr.get("crash_groups", {})
    injury = cr.get("injury_crashes", 0)
    if cr.get("crash_type_recorded"):
        groups = [("pedestrian-involved crashes", ("vehicle", "pedestrian"), "crossing", g.get("pedestrian", 0)),
                  ("rear-end crashes", ("vehicle", "vehicle"), "rear_end", g.get("rear_end", 0)),
                  ("angle and turning crashes", ("vehicle", "vehicle"), "crossing", g.get("angle_turning", 0))]
    else:
        # crash type not recorded (NYC, DC): every injury crash not involving a pedestrian stands in for the
        # angle/turning group, so its estimate is an upper bound
        groups = [("pedestrian-involved injury crashes", ("vehicle", "pedestrian"), "crossing", g.get("pedestrian", 0)),
                  ("rear-end crashes (from contributing factors)", ("vehicle", "vehicle"), "rear_end", g.get("rear_end", 0)),
                  ("other injury crashes (crash type not recorded; upper bound)", ("vehicle", "vehicle"), "crossing",
                   max(injury - g.get("pedestrian", 0), 0))]
    street = d.get("street") or {}
    if street.get("signals", 0) > 0:
        control = "Signalized"
    elif "error" not in street and street.get("stop_signs", 0) > 0:
        control = "Stop-controlled"
    else:  # unknown: only countermeasures that apply to any intersection
        control = "unknown"
    conds = _conditions(d)
    # every precondition is let through; options whose precondition the record does not show are kept and flagged
    # for a site check instead of being dropped
    every = frozenset(i["condition"] for i in countermeasures.psc_items() if i.get("condition"))
    need = {i["name"]: i.get("condition") for i in countermeasures.psc_items()}
    best: dict[str, dict] = {}
    rejected = []
    for label, pair, ctype, n in groups:
        if n <= 0:
            continue
        cands, rej = countermeasures.candidates(cmf, pair, ctype, control=control, conditions=every)
        rejected += [{**r, "for": label} for r in rej]
        for c in cands:
            # a countermeasure that only works in a condition (darkness, wet roads) only acts on that share of
            # the crashes, when the record gives it; otherwise the estimate stays an upper bound
            cond = need.get(c.psc)
            share = {"nighttime": cr.get("dark_share"), "wet or low-friction pavement": cr.get("wet_share")}.get(cond)
            per_year = n / YEARS * (share if share is not None else 1.0)
            avoided = per_year * (1 - c.cmf)
            o = {"countermeasure": c.psc, "cmf_id": c.crfid, "cmf": round(c.cmf, 3), "crf_pct": round(c.crf_pct, 1),
                 "stars": c.stars, "cmf_crash_type": c.crash_type, "cmf_severity": c.severity, "targets": label,
                 "target_crashes_5y": n, "target_crashes_per_year": round(per_year, 1),
                 "condition_share": share if share is not None and cond else None,
                 "expected_crashes_avoided_per_year": round(avoided, 1), **harm.option(avoided, label, cr),
                 "verify_on_site": need.get(c.psc) if need.get(c.psc) and need.get(c.psc) not in conds else None}
            if c.psc not in best or o["expected_crashes_avoided_per_year"] > best[c.psc]["expected_crashes_avoided_per_year"]:
                best[c.psc] = o
    # options whose precondition the record shows (or that have none) first, then those needing a site check
    # a fix the city has already installed here is not proposed again; it is listed as in place
    have = in_place(d)
    opts = sorted((o for o in best.values() if o["countermeasure"] not in have),
                  key=lambda o: (o["verify_on_site"] is not None, -o["expected_crashes_avoided_per_year"]))
    from . import treatments
    for o in opts:  # what the city's own past installs of this fix measured (NML-Bench T11), where it was tested
        ev = treatments.local_evidence(d.get("city"), o["countermeasure"])
        if ev:
            o["local_evidence"] = ev
    return {"options": opts, "in_place": list(have.values()), "rejected": rejected, "control": control,
            "harm": harm.junction(cr, YEARS),
            "conditions_from_record": sorted(conds),
            "method": "expected crashes avoided per year = target crashes per year x (1 - CMF), Highway Safety Manual "
                      "simple method (not Empirical Bayes); dollars use the U.S. DOT's injury-crash value (BCA "
                      "Guidance 2026 Update, Table A-1, 2024 $), break-even cost over 10 years at 7%"}


def _mercator(lat: float, lon: float) -> tuple[float, float]:
    return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi


USGS_IMAGERY = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"


def aerial(lat: float, lon: float, city: str | None, out: Path, size: int = 768, radius_m: float = 90.0) -> Path | None:
    """An aerial photo centred on the junction: a city or state orthophoto from the registry when one covers the
    point, otherwise USGS national imagery (public domain, any US location)."""
    from . import opendata
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    mx, my = _mercator(lat, lon)
    params = {"bbox": f"{mx - radius_m},{my - radius_m},{mx + radius_m},{my + radius_m}", "bboxSR": 3857,
              "imageSR": 3857, "size": f"{size},{size}", "format": "jpg", "f": "image"}
    sources = [(a["endpoint"], a["source"]) for a in opendata.adapters_for(lat, lon, "imagery")]
    sources.append((USGS_IMAGERY, "USGS The National Map imagery"))
    with httpx.Client(timeout=60, headers=context.UA) as c:
        for url, source in sources:
            try:
                r = c.get(url, params=params)
            except httpx.TransportError:
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if img is not None and img.std() > 8:  # a blank or placeholder tile has almost no variation
                    cv2.imwrite(str(out), img)
                    out.with_suffix(".txt").write_text(source)
                    return out
    return None


def street_photo(lat: float, lon: float, out: Path, radius_m: float = 35.0) -> dict | None:
    """The most recent Mapillary street-level photo within radius_m of the junction (Meta's street imagery,
    CC BY-SA), with its capture date and link. Needs MAPILLARY_CLIENT_TOKEN."""
    import os
    token = os.environ.get("MAPILLARY_CLIENT_TOKEN")
    if not token:
        return None
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists():
        return json.loads(meta.read_text())
    d = radius_m / 111_320
    bbox = f"{lon - d / math.cos(math.radians(lat))},{lat - d},{lon + d / math.cos(math.radians(lat))},{lat + d}"
    js, _ = context.fetch("https://graph.mapillary.com/images",
                          {"access_token": token, "bbox": bbox, "limit": 50,
                           "fields": "id,captured_at,thumb_1024_url,computed_geometry,is_pano"})
    imgs = [x for x in js.get("data", []) if x.get("thumb_1024_url") and not x.get("is_pano")]
    if not imgs:
        return None
    pick = max(imgs, key=lambda x: x.get("captured_at") or 0)
    with httpx.Client(timeout=60) as c:
        r = c.get(pick["thumb_1024_url"])
    if r.status_code != 200:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    import datetime as _dt
    info = {"image": str(out), "mapillary_id": pick["id"], "url": f"https://www.mapillary.com/app/?pKey={pick['id']}",
            "captured": _dt.datetime.utcfromtimestamp((pick.get("captured_at") or 0) / 1000).date().isoformat(),
            "licence": "CC BY-SA 4.0, Mapillary contributors"}
    meta.write_text(json.dumps(info))
    return info


INSTRUCTIONS = (
    "You write two sections of a Junction Safety Brief for a city traffic engineer, from the facts given. The ranked "
    "table of fixes is produced separately by code; do not rank or list fixes yourself. record: what the official "
    "record shows (crashes over the period, who was hurt, main factors, whether the city has designated the location, "
    "past projects or treatments, whether there is a plan gap), at most 150 words. limits: the limits of the estimate "
    "(simple method, not Empirical Bayes; do not add fixes together; data gaps in this record), at most 80 words. Use "
    "only numbers in the facts. Call finish once; if it is rejected, fix the errors.")


def fixes_table(opts: dict, n: int = 8) -> str:
    """The ranked fixes, built by code from the option list so the ranking and numbers are exact."""
    rows = ["| # | FHWA Proven Safety Countermeasure | CMF Clearinghouse | Targets | Expected crashes avoided per year | "
            "Harm avoided per year | Pays for itself if it costs under | Site check |",
            "|---|---|---|---|---|---|---|---|"]
    notes = []
    for k, o in enumerate(opts.get("options", [])[:n], 1):
        share = f", {o['condition_share']:.0%} of them in the condition" if o.get("condition_share") else ""
        rows.append(f"| {k} | {o['countermeasure']} | CMF {o['cmf_id']}: {o['cmf']} ({o['stars']}) | {o['targets']}, "
                    f"{o['target_crashes_per_year']}/yr{share} | {o['expected_crashes_avoided_per_year']} | "
                    f"${o['harm_avoided_usd_per_year']:,.0f} | ${o['break_even_cost_usd']:,.0f} | "
                    f"{('verify: ' + o['verify_on_site']) if o.get('verify_on_site') else 'supported by the record'} |")
        if o.get("local_evidence"):
            notes.append(f"_{o['countermeasure']}, tested on this city's own installs: {o['local_evidence']['text']}_")
    h = opts.get("harm")
    head = (f"Injury crashes here cost about ${h['usd_per_year']:,.0f} a year in the U.S. DOT's official values "
            f"({h['injury_crashes_per_year']} a year at ${h['value_per_injury_crash_usd']:,.0f} each, 2024 dollars"
            f"{'; deaths are not valued separately' if h['deaths_in_record'] else ''}).\n\n") if h else ""
    have = "".join(f"\n\nAlready in place (city records): {x['countermeasure']}"
                   f"{' since ' + str(x['year']) if x.get('year') else ''}; not proposed again." for x in opts.get("in_place", []))
    return head + "\n".join(rows) + "".join(f"\n\n{x}" for x in notes) + have + \
        f"\n\n_Method: {opts.get('method', '')}. Do not add fixes together._"


def write_brief(client, facts: dict, tag: str, model: str = "muse-spark-1.3-contributor") -> dict:
    check = context.FactCheck(facts)
    attempts = []

    def finish(record: str, limits: str) -> dict:
        errors = check.text(record) + check.text(limits)
        attempts.append({"record": record, "limits": limits, "errors": errors})
        return {"error": "rejected by the fact checker", "errors": errors} if errors else {"ok": True}

    tool = Tool("finish", "Submit the two sections.", panel._obj({"record": {"type": "string"}, "limits": {"type": "string"}},
                                                                 ["record", "limits"]), finish)
    run = run_agent(client, model, INSTRUCTIONS, "Facts:\n" + json.dumps(facts, default=str), [tool], 6, 0.05,
                    effort="low", tag=tag, escalate_after=3)
    final = next((a for a in reversed(attempts) if not a["errors"]), None)
    text = None
    if final:
        text = (f"# Junction Safety Brief: {facts['junction']}\n\n## What the record shows\n{final['record']}\n\n"
                f"## Ranked fixes\n{fixes_table(facts['fixes'])}\n\n## Limits\n{final['limits']}\n")
    return {"brief": text, "checker_errors": [] if final else (attempts[-1]["errors"] if attempts else ["no brief"]),
            "attempts": len(attempts), "usd": round(run.usd, 5), "stopped": run.stopped}


def build(address: str | None = None, lat: float | None = None, lon: float | None = None, client=None,
          illustrate: bool = False, out_dir: Path | None = None, memo: bool = True) -> dict:
    """The full brief for one junction; the facts, the option ranking and (if asked) the illustration and memo."""
    from .countermeasures import load_cmf
    if address and (lat is None or lon is None):
        lat, lon, name = geocode(address)
    else:
        name = address or f"{lat:.5f}, {lon:.5f}"
    d = context.dossier(lat, lon)
    opts = fix_options(d, load_cmf())
    slug = "".join(ch if ch.isalnum() else "_" for ch in name.split(",")[0].lower())[:60]
    out_dir = out_dir or SETTINGS.runs_dir / "briefs" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = {"junction": name, "dossier": d, "fixes": opts}
    photo = aerial(lat, lon, d.get("city"), out_dir / "aerial.jpg")
    facts["aerial_photo"] = str(photo) if photo else None
    try:  # optional: Mapillary is a free public API and fails now and then
        facts["street_photo"] = street_photo(lat, lon, out_dir / "street.jpg")
    except (RuntimeError, httpx.HTTPError) as e:
        facts["street_photo"] = None
        facts["street_photo_error"] = str(e)[:200]
    if illustrate and photo and opts["options"] and client is not None:
        facts["illustration"] = illustrate_fix(client, photo, opts["options"], out_dir, slug)
    if memo and client is not None:
        facts["brief"] = write_brief(client, {k: v for k, v in facts.items() if k not in ("aerial_photo", "street_photo")},
                                     f"brief {slug}")
    prev = out_dir / "brief.json"
    if "illustration" not in facts and prev.exists() and (out_dir / "fix.jpg").exists():  # keep an earlier drawing
        facts["illustration"] = json.loads(prev.read_text()).get("illustration")
    prev.write_text(json.dumps(facts, indent=1, default=str))
    if facts.get("brief", {}).get("brief"):
        (out_dir / "brief.md").write_text(facts["brief"]["brief"])
    return facts


def illustrate_fix(client, photo: Path, options: list[dict], out_dir: Path, slug: str) -> dict | None:
    """Muse Image draws the highest-ranked illustratable countermeasure on the aerial photo; SAM 3.1 checks it."""
    from . import render
    specs = {i["name"]: i.get("render") for i in countermeasures.psc_items()}
    pick = next((o for o in options if specs.get(o["countermeasure"])), None)
    if pick is None:
        return None
    spec = specs[pick["countermeasure"]]
    before = cv2.imread(str(photo))
    prompt = (f"This is a top-down aerial photo of a road intersection. {spec['prompt']} "
              f"{render.KEEP}")
    edited = render.edit_image(client, before, prompt, f"brief {slug}")
    # keep only the edit around the junction (the photo's centre) and never let it remove or move a real road user:
    # SAM 3.1 masks of cars and people in the original are protected, as in the drone illustrations
    h, w = before.shape[:2]
    keep = np.zeros((h, w), bool)
    for concept in ("car", "person"):
        keep |= render._union_mask(sam_api.segment_image(client, before, concept, f"brief {slug} keep {concept}"), before.shape)
    alpha = render.disc_alpha(before.shape, (w / 2, h / 2), 0.36 * w, 0.06 * w)
    after = render.composite(before, edited, alpha, keep)
    region = alpha > 0.5
    a0 = render.concept_area(client, before, spec["check"], region, f"brief {slug} before")
    a1 = render.concept_area(client, after, spec["check"], region, f"brief {slug} after")
    side = np.hstack([before, render.label(after)])
    path = out_dir / "fix.jpg"
    cv2.imwrite(str(path), side)
    return {"countermeasure": pick["countermeasure"], "cmf_id": pick["cmf_id"], "image": str(path),
            "check_concept": spec["check"], "area_before": a0, "area_after": a1, "check_passed": bool(a1 > a0)}
