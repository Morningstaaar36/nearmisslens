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
from .config import SETTINGS, portable, resolve

YEARS = context.YEARS
OVERPASS_SERVERS = (context.OVERPASS, *context.OVERPASS_MIRRORS)


GEOCODES = Path(__file__).resolve().parent / "data" / "geocodes.json"


def _key(address: str) -> str:
    streets = address.split(",")[0].lower().replace(" and ", " & ")
    return " & ".join(sorted(" ".join(x.split()) for x in streets.split("&")))


def gazetteer() -> dict:
    return json.loads(GEOCODES.read_text()) if GEOCODES.exists() else {}


def save_gazetteer(extra: list[dict] | None = None) -> int:
    """The offline geocode table: every screened priority intersection and the briefs already built, so known
    places need no geocoding service (and replay works for them)."""
    from . import citywide
    table = gazetteer()
    for city, res in citywide.screened():
        for r in res.get("rows", []):
            table[_key(r["name"])] = {"lat": r["lat"], "lon": r["lon"], "name": r["name"], "city": city}
    for p in SETTINGS.runs_dir.glob("briefs/*/brief.json"):
        f = json.loads(p.read_text())
        d = f.get("dossier") or {}
        if d.get("lat") is not None:
            table.setdefault(_key(f["junction"]), {"lat": d["lat"], "lon": d["lon"], "name": f["junction"].split(",")[0],
                                                   "city": d.get("city")})
    for e in extra or []:
        table[_key(e["name"])] = e
    GEOCODES.write_text(json.dumps(dict(sorted(table.items())), indent=0))
    return len(table)


def geocode(address: str) -> tuple[float, float, str]:
    """An address, or an intersection written 'Street A & Street B, City': the offline table first, then Nominatim
    finds the area, and for an intersection OpenStreetMap gives the node shared by the two streets nearest to it."""
    if not address or not address.strip():
        raise ValueError("give an address or an intersection, e.g. 'Street A & Street B, City'")
    known = gazetteer().get(_key(address))
    if known:
        return known["lat"], known["lon"], f"{known['name']}, {address.split(',', 1)[1].strip()}" \
            if "," in address else known["name"]
    if SETTINGS.replay:
        raise ValueError(f"{address!r} is not in the offline set; run without replay to look it up")
    from . import opendata
    country = (json.loads(opendata.REGISTRY.read_text()).get("geocoder") or {}).get("countrycodes", "")
    streets = address.split(",")[0]
    rest = ",".join(address.split(",")[1:])
    first = streets.split("&")[0].strip() if "&" in streets else streets
    js, _ = context.fetch("https://nominatim.openstreetmap.org/search",
                          {"q": f"{first},{rest}", "format": "jsonv2", "limit": 1, "countrycodes": country})
    if not js:
        raise ValueError(f"address not found: {address}")
    lat, lon, name = float(js[0]["lat"]), float(js[0]["lon"]), js[0].get("display_name", address)
    if "&" not in streets:
        return lat, lon, name
    a, b = (x.strip() for x in streets.split("&")[:2])
    jb, _ = context.fetch("https://nominatim.openstreetmap.org/search",
                          {"q": f"{b},{rest}", "format": "jsonv2", "limit": 1, "countrycodes": country})
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
    from . import context as _c
    found = {"lat": lat2, "lon": lon2, "name": f"{a} & {b}", "city": _c.city_of(lat2, lon2)}
    table = gazetteer()  # remembered, so the next lookup (and replay) needs no service
    table[_key(address)] = found
    GEOCODES.write_text(json.dumps(dict(sorted(table.items())), indent=0))
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
    return frozenset(conds)


def site_control(d: dict) -> str:
    """The junction's traffic control from the street layout (OpenStreetMap), or 'unknown'."""
    street = d.get("street") or {}
    if street.get("signals", 0) > 0:
        return "Signalized"
    if "error" not in street and street.get("stop_signs", 0) > 0:
        return "Stop-controlled"
    if "error" not in street and street.get("roads") and not street.get("signals"):
        return "Uncontrolled"
    return "unknown"


def populations(cr: dict) -> dict:
    """Crash counts over the period for each population a CMF can cover; None where the record cannot show it."""
    g = cr.get("crash_groups", {})
    injury = cr.get("injury_crashes", 0)
    typed = bool(cr.get("crash_type_recorded"))
    return {"pedestrian": g.get("pedestrian", 0), "all": injury,
            # rear-end crashes come from crash types where recorded, otherwise from contributing factors
            "rear_end": g.get("rear_end", 0) if (typed or cr.get("factor_counts")) else None,
            "angle": g.get("angle_turning", 0) if typed else None,
            "wet": round(injury * cr["wet_share"], 1) if cr.get("wet_share") is not None else None,
            "night": round(injury * cr["dark_share"], 1) if cr.get("dark_share") is not None else None,
            "walking_along": cr.get("walking_along")}


def fix_options(d: dict, cmf) -> dict:
    """Every FHWA Proven Safety Countermeasure for the junction. A fix is estimated (crashes avoided per year,
    dollars) only when one of its curated CMF records applies to this site's control and to a crash population the
    record shows; otherwise it is listed with the reason and no number. Order: estimated fixes the record supports,
    estimated fixes that need a site check, then fixes with no estimate."""
    cr = d.get("crashes") or {}
    if not cr or "error" in cr:
        return {"options": [], "not_estimated": [], "note": "no crash record available for this location"}
    control = site_control(d)
    conds = _conditions(d)
    pops = populations(cr)
    have = in_place(d)
    from . import treatments
    estimated, not_estimated = [], []
    for item in countermeasures.psc_items():
        name = item["name"]
        if item.get("site_fix") is False or name in have:
            continue
        sel = countermeasures.select(item, control, pops, cmf)
        checks = [c for c in (item.get("condition") if item.get("condition") not in conds else None,
                              item.get("site_check")) if c]
        if not sel["quantified"]:
            not_estimated.append({"countermeasure": name, "quantified": False, "reason": sel["reason"],
                                  "verify_on_site": "; ".join(checks) or None})
            continue
        per_year = sel["target_crashes_5y"] / YEARS
        avoided = per_year * (1 - sel["cmf"])
        o = {"countermeasure": name, "scale": item.get("scale", "low-cost"), **sel, "crf_pct": round(100 * (1 - sel["cmf"]), 1),
             "target_crashes_per_year": round(per_year, 1), "expected_crashes_avoided_per_year": round(avoided, 1),
             **harm.option(avoided, sel["targets"], cr), "verify_on_site": "; ".join(checks) or None}
        ev = treatments.local_evidence(d.get("city"), name)  # this city's own past installs, where tested
        if ev:
            o["local_evidence"] = ev
        st = treatments.program_status(d.get("city"), name)
        if st["status"] in treatments.NOT_SUPPORTED:  # the city tried it and its own record does not show an effect
            # it changes the ranking only when the city's interval rules out the national CMF's effect (or crashes
            # rose); a wide interval from a few sites is shown but carries no weight
            o["local_program"] = {**{k: st[k] for k in ("status", "label", "text", "source", "study", "ci95")},
                                  "contradicts_cmf": st["status"] == "worse" or st["ci95"][0] > sel["cmf"]}
        estimated.append(o)
    # low-cost fixes before reconstructions (which need a design study), then fixes the city's own record does not
    # contradict, then those the crash record supports, then size
    opts = sorted(estimated, key=lambda o: (o["scale"] == "reconstruction",
                                            (o.get("local_program") or {}).get("contradicts_cmf", False),
                                            o["verify_on_site"] is not None, -o["expected_crashes_avoided_per_year"]))
    projects = (d.get("plans") or {}).get("projects", [])
    return {"options": opts, "not_estimated": not_estimated, "in_place": list(have.values()), "control": control,
            "repeat_risk": treatments.repeat_risk(d.get("city"), projects),
            "harm": harm.junction(cr, YEARS), "conditions_from_record": sorted(conds),
            "method": "expected crashes avoided per year = target crashes per year x (1 - CMF), Highway Safety Manual "
                      "simple method (not Empirical Bayes), with the CMF FHWA's fact sheet cites or else the median of "
                      "the curated records that fit the site; dollars use the U.S. DOT's injury-crash value (BCA "
                      "Guidance 2026 Update, Table A-1, 2024 $), break-even cost over 10 years at 7%"}


def _mercator(lat: float, lon: float) -> tuple[float, float]:
    return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi


USGS_IMAGERY = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"


AERIAL_PX, AERIAL_RADIUS_M = 768, 90.0  # the aerial photo: AERIAL_PX square over 2 x AERIAL_RADIUS_M


def aerial(lat: float, lon: float, city: str | None, out: Path, size: int = AERIAL_PX,
           radius_m: float = AERIAL_RADIUS_M) -> Path | None:
    """An aerial photo centred on the junction: a city or state orthophoto from the registry when one covers the
    point, otherwise USGS national imagery (public domain, any US location)."""
    from . import opendata
    if out.exists():
        return out
    if SETTINGS.replay:  # replay never calls a network service
        return None
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
        return {**json.loads(meta.read_text()), "image": portable(str(out))}
    if SETTINGS.replay:  # replay never calls a network service
        return None
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
    info = {"image": portable(str(out)), "mapillary_id": pick["id"], "url": f"https://www.mapillary.com/app/?pKey={pick['id']}",
            "captured": _dt.datetime.utcfromtimestamp((pick.get("captured_at") or 0) / 1000).date().isoformat(),
            "licence": "CC BY-SA 4.0, Mapillary contributors"}
    meta.write_text(portable(json.dumps(info)))
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
        rows.append(f"| {k} | {o['countermeasure']} | CMF {o['cmf_id']}: {o['cmf']} ({o['stars']}; {o['chosen_by']}) | "
                    f"{o['targets']}, {o['target_crashes_per_year']}/yr | {o['expected_crashes_avoided_per_year']} | "
                    f"${o['harm_avoided_usd_per_year']:,.0f} | ${o['break_even_cost_usd']:,.0f} | "
                    f"{'reconstruction, needs a design study; ' if o.get('scale') == 'reconstruction' else ''}"
                    f"{('verify: ' + o['verify_on_site']) if o.get('verify_on_site') else 'supported by the record'} |")
        if o.get("local_evidence"):
            notes.append(f"_{o['countermeasure']}, tested on this city's own installs: {o['local_evidence']['text']}_")
        if o.get("local_program"):
            notes.append(f"_{o['countermeasure']}, tried by this city ({o['local_program']['label']}): "
                         f"{o['local_program']['text']}; "
                         + ("this rules out the national estimate, so it is ranked lower._"
                            if o["local_program"]["contradicts_cmf"] else "too uncertain to change the ranking._"))
    h = opts.get("harm")
    head = (f"Injury crashes here cost about ${h['usd_per_year']:,.0f} a year in the U.S. DOT's official values "
            f"({h['injury_crashes_per_year']} a year at ${h['value_per_injury_crash_usd']:,.0f} each, 2024 dollars"
            f"{'; deaths are not valued separately' if h['deaths_in_record'] else ''}).\n\n") if h else ""
    have = "".join(f"\n\nAlready in place (city records): {x['countermeasure']}"
                   f"{' since ' + str(x['year']) if x.get('year') else ''}; not proposed again." for x in opts.get("in_place", []))
    skipped = opts.get("not_estimated") or []
    none = ("\n\nNot estimated here: " + "; ".join(f"{x['countermeasure']} ({x['reason']})" for x in skipped) + ".") \
        if skipped else ""
    repeat = "".join(f"\n\n**Tried here before:** {x['text']}" for x in opts.get("repeat_risk") or [])
    return head + "\n".join(rows) + "".join(f"\n\n{x}" for x in notes) + have + repeat + none + \
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
    facts["aerial_photo"] = portable(str(photo)) if photo else None
    try:  # optional: Mapillary is a free public API and fails now and then
        facts["street_photo"] = street_photo(lat, lon, out_dir / "street.jpg")
    except (RuntimeError, httpx.HTTPError) as e:
        facts["street_photo"] = None
        facts["street_photo_error"] = str(e)[:200]
    if illustrate and photo and opts["options"] and client is not None:
        facts["illustration"] = illustrate_fix(client, resolve(photo), opts["options"], out_dir, slug)
    if memo and client is not None:
        facts["brief"] = write_brief(client, {k: v for k, v in facts.items() if k not in ("aerial_photo", "street_photo")},
                                     f"brief {slug}")
    prev = out_dir / "brief.json"
    if "illustration" not in facts and prev.exists() and (out_dir / "fix.jpg").exists():  # keep an earlier drawing
        kept = json.loads(prev.read_text()).get("illustration")
        facts["illustration"] = {**kept, "image": portable(str(out_dir / "fix.jpg"))} if kept else None  # paths move with the runs dir
    prev.write_text(portable(json.dumps(facts, indent=1, default=str)))
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
    return {"countermeasure": pick["countermeasure"], "cmf_id": pick["cmf_id"], "image": portable(str(path)),
            "check_concept": spec["check"], "area_before": a0, "area_after": a1, "check_passed": bool(a1 > a0)}
