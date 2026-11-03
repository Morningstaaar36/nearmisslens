"""The desk: Muse Spark runs a real case from the live world, and code referees (NML-Bench T21).

Muse Spark (Meta Model API, Responses) plans the investigation and chooses every step:
- `web_search` (Meta) finds the incident or the claim on the live web and opens the page;
- tool search loads, on demand, the city's open datasets from the registry (one deferred tool per dataset, generated
  from registry.json, never written by hand), each returning the exact query it ran as its receipt;
- `investigate` builds the corner's full case with the engineer's six checked tools (and, if asked, a request letter
  drafted by Muse Spark Open on Baseten and number-checked);
- `check_claim` tests a sentence from the source against the corner's receipts (the number checker, then Muse Spark
  reading it into assertions that code verifies);
- `program_record` answers "did the city's program work" from the causal gate.
It publishes only through `finish`, and finish refuses a finding whose numbers do not match its receipt, a fix stated
without its site check, causal wording, and any quote that is not in the page it cites (the citation gate)."""
from __future__ import annotations

import html
import json
import re
import time

from . import context, engineer, opendata, treatments
from .agent import Tool, run_agent
from .cache import atomic_write
from .config import MODELS, SETTINGS
from .config import asof as config_asof

MODEL = MODELS["orchestrator"]
GEO_KINDS = ("crash", "project", "designation", "crash_detail")  # dataset kinds that can be queried around a point
SNAP_M = 150.0  # an address (not an intersection) is investigated at the nearest screened corner within this distance
INTERSECTION = re.compile(r"&|\s(and|at)\s|/", re.I)
INSTRUCTIONS = (
    "You work for a city's street-safety team. Given a real-world input (a news story, a statement, a resident's "
    "report, a corner or a city), find the facts, investigate the corner and check what was claimed. Use web_search "
    "to find the source, then read_page to read it: quote only sentences copied from read_page's text, never from "
    "memory or the search snippet. Call investigate once, on the intersection the source names (two cross streets). "
    "Load the city's open datasets with tool search when you need more records. Use check_claim on the numbers the "
    "source states (a few, not every sentence) and program_record when a source credits a safety program. "
    "Findings are plain sentences, each citing what it rests on: a record number cites the D receipt that holds it "
    "(investigate lists its claims with their receipts: use them as written); a claim verdict cites the check_claim "
    "receipt; a fact from the source (a name, an age, a time) cites the source's URL. Cover the injury crashes and "
    "what they have in common, the city's verdict on the relevant program, the fix the evidence supports and its "
    "evidence tier, who owns the road, and the verdict on each claim you checked. Never write 'caused', 'proves' or "
    "'will'. Sources: each with its URL and an exact quote from that page. Before finish, run check_findings once on "
    "the whole draft and fix what it names; stay on one intersection.")


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def page_text(url: str) -> str:
    """A web page's visible text (cached on disk like every fetch), for the citation gate."""
    import httpx
    key = context.hashlib.sha256(url.encode()).hexdigest()[:24]
    path = context._cache_dir() / f"page_{key}.txt"
    from .config import SETTINGS
    cached = path.read_text() if path.exists() else None
    if cached is not None and (SETTINGS.replay or len(cached) >= READABLE):
        return cached  # a short page saved by an older version is fetched again when live
    if SETTINGS.replay:
        return ""
    if not public_url(url):
        return ""
    try:  # our own, honest user agent: a site that refuses automated readers is respected, and its quote is
        # published marked unverified rather than fetched another way
        with httpx.Client(headers=context.UA, timeout=30, follow_redirects=True) as c:
            r = c.get(url)
    except httpx.HTTPError:
        return ""  # not cached: a network failure is not remembered as the page's text
    if r.status_code != 200:
        return ""  # a refusal or a missing page is not cached as the page's text
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    atomic_write(path, text)
    return text


def public_url(url: str) -> bool:
    """Only http(s) pages on public hosts are fetched: a URL the model read on the web never reaches this machine's
    own network (localhost, private ranges, cloud metadata)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(u.hostname, None)}
    except OSError:
        return False
    return all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


def image_bytes(url: str) -> bytes | None:
    """A photo's bytes, cached on disk like every fetch, so a replay never goes to the network (None if unavailable)."""
    import httpx
    from .config import SETTINGS
    path = context._cache_dir() / f"img_{context.hashlib.sha256(url.encode()).hexdigest()[:24]}.bin"
    if path.exists():
        return path.read_bytes()
    if SETTINGS.replay or not public_url(url):
        return None
    try:
        with httpx.Client(headers=context.UA, timeout=30, follow_redirects=True) as c:
            r = c.get(url)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    atomic_write(path, r.content)
    return r.content


def _norm(s: str) -> str:
    """Lower case, letters and digits only, single spaces: a quote matches the page despite punctuation and quotes."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


READABLE = 1500  # characters of visible text below which a page did not load (blocked, script-only or a file)


def text_of(url: str, known: dict | None = None) -> str | None:
    """The text the gate checks a source against: a record the desk was handed (e.g. the 311 report itself), or the
    page as fetched; None when the page could not be read here."""
    if known and url in known:
        return known[url]
    text = page_text(url)
    return text if len(text) >= READABLE else None


def quote_check(quote: str, url: str, known: dict | None = None) -> str:
    """'verified' (the quote is in the page), 'absent' (the page loaded and the quote is not in it) or 'unreadable'
    (the page could not be read here, so the quote is published marked unverified, never refused for that alone)."""
    text = text_of(url, known)
    if text is None:
        return "unreadable"
    q = _norm(redact(quote))  # a plate is removed from what we keep, so it is removed from the page compared too
    return "verified" if len(q) >= 12 and q in _norm(redact(text)) else "absent"


def quote_in_page(quote: str, url: str) -> bool:
    return quote_check(quote, url) == "verified"


class Desk:
    """The case being worked: receipts (id -> tool, data, query), sources, and the corner's engineer report."""

    def __init__(self, city: str | None = None):
        self.city = city
        self.receipts: dict[str, dict] = {}
        self.report: dict | None = None
        self.web: list[dict] = []
        self.places: set[str] = set()
        self.pages: dict[str, str] = {}  # records handed to the desk with the task (url -> text), e.g. a 311 report
        self.claim_checks = 0
        self.reads = 0

    def receipt(self, tool: str, data, query: str | None = None) -> str:
        rid = f"D{len(self.receipts) + 1}"
        self.receipts[rid] = {"tool": tool, "data": data, **({"query": query} if query else {})}
        return rid

    def collect(self, resp: dict) -> None:
        for o in resp.get("output", []):
            if o.get("type") == "web_search_call":
                self.web.append({"action": o.get("action"), "results": [{k: r.get(k) for k in ("title", "url")}
                                                                       for r in o.get("results") or []][:8]})


def dataset_tools(city: str, desk: Desk) -> tuple[dict | None, list[Tool]]:
    """One deferred tool per geocoded registry dataset of the city, grouped in a namespace for tool search."""
    ns = f"{city}_open_data"
    found = [a for a in opendata.load_registry() if a.get("city") == city and a.get("kind") in GEO_KINDS
             and a.get("platform") in ("socrata", "arcgis") and (a.get("geo_field") or a.get("lat_field") or a["platform"] == "arcgis")]
    params = _obj({"lat": {"type": "number"}, "lon": {"type": "number"}, "radius_m": {"type": "number"}},
                  ["lat", "lon", "radius_m"])
    tools, specs = [], []
    for a in found:
        name = re.sub(r"[^a-z0-9_]", "_", a["id"].lower())
        desc = f"{a.get('label') or a['kind']}: {a.get('source', a['id'])}. Records within radius_m of a point."

        def fn(lat, lon, radius_m, a=a, name=name):
            r = max(10.0, min(float(radius_m), 300.0))
            rows = opendata.rows_near(a, float(lat), float(lon), r)
            query = (f"{a['endpoint']}?$where=within_circle({a.get('geo_field')},{lat},{lon},{r})" if a["platform"] == "socrata"
                     else f"{a['endpoint']}/query (point {lat},{lon}, {r} m)")
            keep = [k for k in (a.get("date_field"), a.get("name_field"), a.get("label_field")) if k]
            sample = [{k: row.get(k) for k in keep} if keep else {k: v for k, v in list(row.items())[:6]} for row in rows[:5]]
            return {"receipt": desk.receipt(f"{ns}.{name}", {"records": len(rows)}, query), "records": len(rows),
                    "sample": sample}
        tools.append(Tool(f"{ns}.{name}", desc, params, fn))
        specs.append({"type": "function", "name": name, "description": desc, "defer_loading": True, "parameters": params})
    if not specs:
        return None, []
    space = {"type": "namespace", "name": ns, "description": f"{city} open datasets about streets: "
             + "; ".join((a.get("label") or a["kind"]) for a in found)[:400], "tools": specs}
    return space, tools


def core_tools(desk: Desk, letter_client=None, model_check_client=None, model_client=None,
               max_reads: int | None = None, sources_name_corner: bool = False) -> list[Tool]:
    txt, num = {"type": "string"}, {"type": "number"}

    def investigate(address: str, draft_letter: bool):
        from . import brief
        letters = letter_client if draft_letter else None
        snapped, rep, point = None, None, None
        if INTERSECTION.search(address.split(",")[0]):
            last = None
            # "Bay Pkwy and Cropsey Ave" -> "Bay Parkway & Cropsey Avenue"; the '&' forms first, because a free-text
            # search for "22nd and Mission" returns the nearest business, not the intersection
            for variant in sorted(brief.address_variants(address), key=lambda v: "&" not in v.split(",")[0]):
                try:
                    r = engineer.plan(variant, letter_client=letters)
                except ValueError as e:
                    last = e
                    continue
                j = r["junction"]
                if "&" in j["name"].split(",")[0]:  # the geocoder found the two streets' shared node
                    rep = r
                    break
                point = point or (j["lat"], j["lon"])  # a place near it: snapped below to a screened corner, or refused
            if rep is None and point is None:
                raise last
        else:  # a street address or a place name: the corner is the nearest screened intersection, or none
            lat, lon, _ = brief.geocode(address)
            point = (lat, lon)
        if rep is None:
            lat, lon = point
            near = nearest_corner(desk.city, lat, lon)
            if near is None or near[1] > SNAP_M:
                gap = f"; the nearest screened corner is {near[0]['name']} at {near[1]:.0f} m" if near else ""
                return {"error": f"{address!r} is not an intersection{gap}. Give the two cross streets named in the "
                                 "source ('Street A & Street B, City'), or use the nearest corner if the source names one."}
            j, dist = near
            rep = engineer.investigate(engineer.Desk(), address, j["name"], j["lat"], j["lon"], letter_client=letters)
            snapped = {"from": address, "to": j["name"], "metres": round(dist)}
        if desk.report is not None and rep["junction"]["name"] != desk.report["junction"]["name"]:
            return {"error": f"this case is about {desk.report['junction']['name']}; stay on one intersection "
                             "(its receipts are listed above)"}
        desk.report = rep
        desk.places.add(rep["junction"]["name"].split(",")[0])
        ids = {}
        for r in rep["receipts"]:
            if r["tool"] in rep["findings"]:
                ids[r["tool"]] = desk.receipt(r["tool"], rep["findings"][r["tool"]])
        letter = (rep["findings"].get("draft_request") or {}).get("letter")
        # each code-written claim with the receipt id it rests on, so the agent cites the receipt that holds a number
        tool_rid = {r["id"]: ids.get(r["tool"]) for r in rep["receipts"]}
        return {"corner": rep["junction"]["name"], "receipts": ids, **({"snapped": snapped} if snapped else {}),
                "claims_with_receipts": [{"text": c["text"], "receipt": tool_rid.get(c["receipt"])} for c in rep["claims"]][:16],
                "note": "cite each number with the receipt listed next to the claim it comes from",
                **({"letter": letter} if letter else {})}

    def read_page(url: str, find: str):
        """The page's text exactly as the citation gate reads it: the sentences that mention `find`, else the start.
        With max_reads, the finding phase ends there: reading is capped so a case cannot spend its turns on sources."""
        desk.reads += 1
        if max_reads is not None and desk.reads > max_reads:
            return {"error": f"{max_reads} pages read already: investigate the intersection the best source names, "
                             "check its numbers and finish with what you have read"}
        text = text_of(url, desk.pages)
        if text is None:
            return {"readable": False, "note": "this page cannot be read here; cite another page that reports it"}
        words = [w for w in _norm(find).split() if len(w) > 2]
        sents = re.split(r"(?<=[.!?])\s+", text)
        hits = [x for x in sents if words and any(w in _norm(x).split() for w in words)]
        body = " ".join(hits)[:2500] if hits else text[:2500]
        return {"readable": True, "chars": len(text), "text": body}

    def check_claim(text: str, receipt: str):
        d = desk.receipts.get(receipt)
        if not d:
            return {"error": f"no receipt {receipt}"}
        desk.claim_checks += 1
        if desk.claim_checks > MAX_CLAIM_CHECKS:
            return {"error": f"{MAX_CLAIM_CHECKS} claims checked already: write the findings and run check_findings"}
        verdict, reasons, flags = claim_verdict(text, d["data"], _places(desk), model_check_client)
        asof = (desk.report or {}).get("asof")
        frame = (f"the record counts police-reported crashes within {context.CRASH_RADIUS_M:g} m of this corner over "
                 f"{context.YEARS} years to {asof or 'its as-of date'}; a source counting another area or period can differ")
        rid = desk.receipt("check_claim", {"claim": text, "verdict": verdict, "reasons": reasons, "flags": flags,
                                           "against": receipt, "frame": frame})
        return {"verdict": verdict, "reasons": reasons, **({"model_read_flags": flags} if flags else {}),
                "receipt": rid, "record_frame": frame,
                "note": f"a finding about this claim cites {rid} and states the verdict"}

    def program_record(city: str, countermeasure: str):
        st = program_match(desk.city or city, countermeasure)
        return {"receipt": desk.receipt("program_record", st),
                **{k: st.get(k) for k in ("status", "label", "text", "sites", "source", "programs_with_studies")}}

    def gate(summary: str, findings: list[dict], sources: list[dict]) -> tuple[list[str], list[dict]]:
        errors = []
        all_options = {"options": [o for r in desk.receipts.values() if isinstance(r["data"], dict)
                                   for o in r["data"].get("options") or []]}
        urls = {s.get("url") for s in sources}
        record_numbers = 0
        for k, f in enumerate(findings, 1):
            rid, t = f.get("receipt"), engineer.strip_places(f.get("text", ""), _places(desk))
            if rid in urls:  # a fact from the source: its numbers must be on that page
                page = text_of(rid, desk.pages)
                if page is None:
                    errors.append(f"finding {k}: {rid} cannot be read here, so facts from it cannot be checked; "
                                  "cite a page that can be read")
                else:
                    errors += [f"finding {k}: {n} is not on the page it cites" for n in numbers_in(t)
                               if n not in numbers_in(page)]
                errors += [f"finding {k}: {e}" for e in engineer.wording(t)]
                continue
            d = desk.receipts.get(rid)
            if not d:
                errors.append(f"finding {k} cites no receipt (got {rid!r}); cite a D receipt or a source URL")
                continue
            if d["tool"] == "check_claim":  # a claim verdict: it must state the verdict the check gave
                errors += [f"finding {k}: {e}" for e in verdict_errors(t, d["data"])]
                continue
            if numbers_in(t):
                record_numbers += 1
            numbers = context.FactCheck(d["data"]).text(t)
            if numbers and re.search(r"\d", t):  # structured criticism: does another receipt hold these numbers?
                other = next((rid for rid, o in desk.receipts.items() if rid != f.get("receipt")
                              and o["tool"] != "photo_read" and not context.FactCheck(o["data"]).text(t)), None)
                if other:
                    numbers = [f"these numbers are in {other} ({desk.receipts[other]['tool']}), not "
                               f"{f.get('receipt')}: cite {other}"]
            # a fix that holds only after a site check must say so, whichever receipt the finding cites
            errs = numbers + engineer.conditional_fix_errors(t, all_options) + engineer.wording(t)
            errors += [f"finding {k}: {e}" for e in errs]
        checked = []
        for k, s in enumerate(sources, 1):
            state = quote_check(s.get("quote", ""), s.get("url", ""), desk.pages)
            if state == "absent":
                errors.append(f"source {k}: the quote is not in the page at {s.get('url')} (copy it exactly)")
            elif sources_name_corner and state == "verified" and desk.report and \
                    not names_corner(text_of(s.get("url", ""), desk.pages) or "", desk.report["junction"]["name"]):
                errors.append(f"source {k}: the page at {s.get('url')} does not name {desk.report['junction']['name']}; "
                              "a quote on its page is not about this corner: cite a page that names it, or leave it out")
            checked.append({**s, "quote_check": state})
        errors += [f"summary: {e}" for e in engineer.wording(summary)]
        texts = [summary] + [f.get("text", "") for f in findings] + [s.get("quote", "") for s in sources]
        if any(has_plate(t) for t in texts):
            errors.append("a licence plate is written out: never publish one (choose another quote, or leave it out)")
        if record_numbers < 3:  # a publishable case states the record's numbers, not just that a case exists
            errors.append(f"only {record_numbers} findings give a number from the record (years do not count); give at "
                          "least 3, citing their D receipts (investigate lists them: crashes, what they have in "
                          "common, the program verdict, the fix and its evidence)")
        if not sources:
            errors.append("no source: cite the page the input came from, with an exact quote")
        elif not any(c["quote_check"] == "verified" for c in checked):
            errors.append("no quote could be checked against its page: read a page that can be read (read_page) and "
                          "copy a sentence from it exactly")
        return errors, checked

    def finish(summary: str, findings: list[dict], sources: list[dict]):
        errors, checked = gate(summary, findings, sources)
        if errors:
            return {"error": "refused by the publish gate", "errors": errors[:12]}
        desk.final = {"summary": summary, "findings": findings, "sources": checked}
        return {"ok": True}

    def check_findings(summary: str, findings: list[dict], sources: list[dict]):
        """The publish gate as a dry run, in one call: what would be refused and why (no refusal is counted)."""
        errors, _ = gate(summary, findings, sources)
        return {"would_publish": not errors, "problems": errors[:15]}

    def view_photo(url: str, question: str):
        """Muse Spark looks at a photo (low effort: seeing does not improve with more thinking); code first refuses
        an unreadable or dark image (evidence or abstain). The answer is a model observation, labelled as such."""
        import cv2
        import numpy as np
        from . import sam_api
        from .cost import token_usd
        from .meta_client import output_text
        from .config import DARK_MEAN
        raw = image_bytes(url)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
        if img is None or float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean()) < DARK_MEAN:
            return {"answer": "unsure", "why": "the photo could not be read or is too dark", "receipt": desk.receipt("photo_read", {"readable": False})}
        h, w = img.shape[:2]
        if max(h, w) > 1280:
            img = cv2.resize(img, (int(w * 1280 / max(h, w)), int(h * 1280 / max(h, w))))
        schema = _obj({"shows": txt, "answer": {"type": "string", "enum": ["yes", "no", "unsure"]},
                       "who_is_at_risk": {"type": "array", "items": txt}}, ["shows", "answer", "who_is_at_risk"])
        model = MODELS["vision"]
        inst = ("Describe what this street photo shows in one sentence, then answer the question yes, no or unsure "
                "(unsure if the photo does not show it clearly), and list who it puts at risk. Never read out a licence "
                "plate, a name or anything else that identifies a person or a vehicle.")
        url_ = sam_api.png_data_url(img)
        req = {"model": model, "q": question, "img": context.hashlib.sha256(url_.encode()).hexdigest()}
        payload = {"model": model, "reasoning": {"effort": "low"}, "max_output_tokens": 1500, "instructions": inst,
                   "text": {"format": {"type": "json_schema", "name": "photo", "schema": schema, "strict": True}},
                   "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": question},
                                                                             {"type": "input_image", "image_url": url_}]}]}
        resp = model_client.cached("photo_read", req, lambda: model_client.create_response(payload),
                                   lambda r: (token_usd(model, (r.get("usage") or {}).get("input_tokens", 0),
                                                        (r.get("usage") or {}).get("output_tokens", 0)), model, {}),
                                   0.005, "desk photo", require_text=True)
        ans = json.loads(output_text(resp))
        return {**ans, "note": "a model observation of the photo, not a checked fact",
                "receipt": desk.receipt("photo_read", {"readable": True, **ans})}

    claim = {"type": "array", "items": _obj({"text": txt, "receipt": txt}, ["text", "receipt"])}
    source = {"type": "array", "items": _obj({"url": txt, "quote": txt}, ["url", "quote"])}
    return [
        Tool("read_page", "Read a web page as the citation gate reads it: the sentences mentioning `find` (or the "
             "start). Quote only from this text.", _obj({"url": txt, "find": txt}, ["url", "find"]), read_page),
        Tool("investigate", "Build the checked case for an intersection: crashes, patterns, the city's programs, "
             "fixes by evidence, road owners; optionally a number-checked request letter.",
             _obj({"address": txt, "draft_letter": {"type": "boolean"}}, ["address", "draft_letter"]), investigate),
        Tool("check_claim", "Check one number-bearing sentence from the source against a D receipt; returns a verdict "
             "and its own receipt.",
             _obj({"text": txt, "receipt": txt}, ["text", "receipt"]), check_claim),
        Tool("view_photo", "Look at a photo (e.g. from a resident's report) and answer a question about it.",
             _obj({"url": txt, "question": txt}, ["url", "question"]), view_photo),
        Tool("program_record", "What the city's own crash record says about a safety program (the causal gate); "
             "name the program or countermeasure as the source does.",
             _obj({"city": txt, "countermeasure": txt}, ["city", "countermeasure"]), program_record),
        Tool("check_findings", "Dry-run the publish gate on a whole draft (summary, findings, sources) in one call; "
             "fix what it names, then call finish.",
             _obj({"summary": txt, "findings": claim, "sources": source}, ["summary", "findings", "sources"]), check_findings),
        Tool("finish", "Publish: summary, findings citing receipts, and sources with exact quotes.",
             _obj({"summary": txt, "findings": claim, "sources": source}, ["summary", "findings", "sources"]), finish),
    ]


MAX_CLAIM_CHECKS = 6  # claims checked per case: enough for a source's numbers, too few to probe the gate with
YEAR = re.compile(r"\b(19|20)\d\d\b")
DIFFERS = ("but the record has", "is not the record's number", "written as a count")
UNTESTABLE = ("is not in the dossier", "not covered", "is not a share or change", "the record does not show",
              "does not show")
VERDICT_WORDS = {"consistent with the record": ("consistent", "matches", "agrees"),
                 "differs from the record": ("differs", "does not match", "different"),
                 "cannot be checked against this record": ("cannot be checked", "not in the public record",
                                                           "not in the record", "cannot be tested", "untestable"),
                 "overstates what the record can show": ("overstate",)}


PLATE = re.compile(r"\b(?:plate|licen[cs]e(?:\s+plate)?|tag)\b(?:\s+(?:number|no\.?|#))?\s*:?\s*([A-Z0-9][A-Z0-9 -]{3,8}[A-Z0-9])\b",
                   re.I)


def has_plate(text: str) -> bool:
    """A licence plate written out ("CA plate 7ABC123"): never published, even when the source printed it."""
    return any(re.search(r"\d", m.group(1)) for m in PLATE.finditer(text or ""))


STREET_WORDS = {"street", "st", "avenue", "ave", "av", "boulevard", "blvd", "road", "rd", "place", "pl", "drive", "dr",
                "lane", "ln", "court", "ct", "way", "parkway", "pkwy", "highway", "hwy", "terrace", "square", "north",
                "south", "east", "west", "n", "s", "e", "w", "nw", "ne", "sw", "se", "northwest", "northeast", "southwest",
                "southeast", "the", "of"}


def names_corner(text: str, corner: str) -> bool:
    """Whether a page names at least one of the corner's streets by its own words ('Pennsylvania', '8th'), so a
    source about another crash cannot stand behind this corner's case."""
    page = " " + _norm(text) + " "
    for street in re.split(r"\s*&\s*", corner.split(",")[0]):
        core = [w for w in _norm(street).split() if w not in STREET_WORDS]
        if core and all(f" {w} " in page for w in core):
            return True
    return False


def redact(text: str) -> str:
    return PLATE.sub(lambda m: m.group(0).replace(m.group(1), "[plate removed]") if re.search(r"\d", m.group(1))
                     else m.group(0), text or "")


def numbers_in(text: str) -> set[str]:
    """The numbers a sentence states, years left out (a year places a fact; it is not a count from the record)."""
    t = YEAR.sub(" ", text or "")
    return {n.replace(",", "").rstrip(".").removesuffix(".0") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}


NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                             "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS |= {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
WORD_COUNT = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b(?=\s+(?:[\w-]+\s+){0,2}?(?:people|persons?|pedestrians?|"
                        r"cyclists?|bicyclists?|motorists?|drivers?|riders?|women|men|children|kids|crash(?:es)?|"
                        r"collisions?|deaths?|fatalities|intersections|sites|locations|killed|injured|hurt|dead|died)\b)",
                        re.I)
# a sentence about one crash ("struck by a car", "the July 27 crash"): its counts are that crash's people, not the
# record's counts over five years
INCIDENT = re.compile(r"\b(?:the|a|this|that)\s+(?:[\w,-]+\s+){0,4}?(?:crash|collision|incident)\b|"
                      r"\bby an?\s+(?:[\w-]+\s+){0,3}?(?:car|driver|vehicle|truck|suv|sedan|bus|van|motorist)\b", re.I)
PEOPLE_LABELS = ("deaths", "pedestrians killed", "cyclists killed", "pedestrians injured", "cyclists injured")
COST = re.compile(r"\b(cost|costs|harm|worth|value|economic)\b", re.I)
AREA = re.compile(r"\bcorridor\b|\balong\b|\bcity-?wide\b|\bacross (?:the )?city\b|\bhigh[- ]injury network\b|"
                  r"\bneighbou?rhood\b|\bdistrict\b|\bwards?\b|\b(?:total )?traffic (?:deaths|fatalities)\b|"
                  r"\bvision zero (?:report|data|update)\b", re.I)  # a city's own totals are not one corner's
OTHER_PERIOD = re.compile(r"\b(?:last|past|previous)\s+(?:one|two|three|four|six|seven|eight|nine|ten|1|2|3|4|6|7|8|9|10)"
                          r"\s+years?\b|\b(?:last|past|this)\s+(?:year|month|week)\b", re.I)  # not the record's five years
SEVERITY = re.compile(r"\bKSI\b|serious(?:ly)? injur|severe(?:ly)? injur|severe crash", re.I)
MISMATCH = re.compile(r"^(\S+) is not the record's number of (.+?)(?: \(the record has.*| for what this sentence names)?$")


def words_to_digits(text: str) -> str:
    """"Two women are dead" -> "2 women are dead": a count written as a word is checked like one written as a digit."""
    return WORD_COUNT.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text or "")


def _record_has(fc: context.FactCheck, label: str) -> bool:
    pattern = next((p for n, _, _, p in context.LABELS if n == label), None)
    if label in ("deaths", "pedestrians killed", "cyclists killed"):
        pattern = r"killed|death|fatal|injury_crash"  # a crash record lists only non-zero deaths: absent means none
    return pattern is None or any(re.search(pattern, k) for _, k, _ in fc.paths)


def claim_errors(fc: context.FactCheck, text: str) -> list[str]:
    """The number checker's objections to a source's sentence, with the ones a crash record cannot decide said so:
    a label this receipt has no field for, a dollar figure that is not a crash cost (a budget, a grant), and the
    people in one crash set against five years of crashes."""
    incident = bool(INCIDENT.search(text))
    start = window_start(fc)
    early = [y for y in map(int, re.findall(r"\b(?:19|20)\d\d\b", text)) if start and y < start]
    out = []
    for e in fc.text(text):
        if re.fullmatch(r"number (?:19|20)\d\d is not in the dossier", e):
            continue  # a year places a fact; it is not a count
        m = MISMATCH.match(e)
        if m:
            n, label = m.groups()
            if early:
                e = f"{n}: the record does not show {early[0]} (its window starts in {start})"
            elif OTHER_PERIOD.search(text):
                e = (f"{n}: the record does not show {OTHER_PERIOD.search(text).group(0)} "
                     f"(it counts {context.YEARS} years to its as-of date)")
            elif AREA.search(text):
                e = f"{n}: the record does not show this area (it counts crashes within {context.CRASH_RADIUS_M:g} m of the corner)"
            elif label == "dollars" and not COST.search(text):
                e = f"{n}: the record does not show this sum (it holds crash costs, not budgets or grants)"
            elif SEVERITY.search(text) and not any(re.search(r"serious|severe|ksi", k, re.I) for _, k, _ in fc.paths):
                e = f"{n}: the record does not show serious injuries apart from other injuries"
            elif label == "sites" and not fc._bound(text):
                e = f"{n}: the record does not show this set of places (its sites are a program's study sites)"
            elif incident and label in PEOPLE_LABELS:
                e = (f"{n}: the record does not show the people in one crash (it counts all crashes within "
                     f"{context.CRASH_RADIUS_M:g} m over {context.YEARS} years)")
            elif not _record_has(fc, label):
                e = f"{n}: the record does not show {label}"
        out.append(e)
    return list(dict.fromkeys(out))


LOWER = re.compile(r"\b(?:at least|more than|over|upwards of)\s+$", re.I)
UPPER = re.compile(r"\b(?:fewer than|less than|under|at most|up to)\s+$", re.I)
LOWER_AFTER, UPPER_AFTER = re.compile(r"^\s*(?:or more\b|\+)", re.I), re.compile(r"^\s*or (?:fewer|less)\b", re.I)
CRITERION = re.compile(r"\b(?:where|with|having|that had|that have)\s+(?:[\w-]+\s+){0,2}(?:at least|more than|over|"
                       r"fewer than|less than|under|at most|up to)?\s*$", re.I)


def resolve_bounds(fc: context.FactCheck, text: str) -> str:
    """"At least 106 crashes" is a bound, not a count: it holds where the record's count for what it names is 106 or
    more (the sentence is rewritten with that count, so the checker tests the label); "intersections where five or
    more were killed" is a threshold that defines a group, so it is no count at all."""
    for m in reversed(list(re.finditer(r"\d[\d,]*(?:\.\d+)?", text))):
        head, tail = text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 12]
        low, up = LOWER.search(head) or LOWER_AFTER.match(tail), UPPER.search(head) or UPPER_AFTER.match(tail)
        if not (low or up) or YEAR.fullmatch(m.group(0)):
            continue
        if CRITERION.search(head):
            text = text[:m.start()] + "several" + text[m.end():]
            continue
        n = float(m.group(0).replace(",", ""))
        for v in sorted(fc.known, reverse=bool(up)):
            if (v >= n if low else v <= n) and v == int(v):
                probe = text[:m.start()] + f"{v:g}" + text[m.end():]
                if not any(c in e for e in claim_errors(fc, probe) for c in DIFFERS):
                    text = probe
                    break
    return text


def window_start(fc: context.FactCheck) -> int | None:
    """The first year of the record's window (its 'since' date), when the receipt states one."""
    return int(fc.since[:4]) if fc.since else None


def checked_numbers(fc: context.FactCheck, text: str) -> list[str]:
    """The numbers in a sentence the record actually tests: a different value in their place would be refused as
    not the record's number. A number that merely appears somewhere in the record (a time, an address, a coincidence)
    tests nothing, so a sentence with none of these is not 'consistent', only uncheckable."""
    out = []
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        if YEAR.fullmatch(m.group(0)):
            continue
        probe = text[:m.start()] + "987654" + text[m.end():]
        if text[max(0, m.start() - 2):m.start()].rstrip().endswith("$"):  # a crash cost, scaled as written
            scale = {"million": 1e6, "thousand": 1e3}.get((re.match(r"\s*(million|thousand)", text[m.end():]) or
                                                          [None, ""])[1], 1)
            v = float(m.group(0).replace(",", "")) * scale
            if COST.search(text) and any(abs(x - v) <= 0.05 * max(v, 1) for x in fc.by_label["dollars"]):
                out.append(m.group(0))
            continue
        if text[m.end():m.end() + 2].lstrip().startswith("%"):
            if fc._bound(text) and "is not a share or change" in " ".join(fc.text(probe)):
                out.append(m.group(0))  # a share of something the sentence names that the record holds
            continue
        if any(c in e for e in claim_errors(fc, probe) for c in DIFFERS):
            out.append(m.group(0))
    return out


def claim_verdict(text: str, data: dict, places, client=None) -> tuple[str, list[str], list[str]]:
    """A source's sentence against a receipt, decided by the number checker: 'differs' only when the record has a
    different value for what the sentence names (the source may count another window or area: the verdict says so,
    never "false"); 'cannot be checked' when the record has nothing on it (a victim's age, a corridor-wide total, a
    grant, the people in one crash) or when no number in it is one the record tests; 'consistent' only when at least
    one of its numbers was tested and matched. The model-read check (T20b) refuses about a quarter of true claims, so
    it never decides a verdict: what it objects to is returned as flags."""
    overstated = engineer.wording(text)
    fc = context.FactCheck(data)
    t = engineer.strip_places(text, places)
    t = re.sub(r"\bcollisions?\b", lambda m: "crashes" if m.group(0).endswith("s") else "crash", t, flags=re.I)
    t = resolve_bounds(fc, words_to_digits(re.sub(r"\s+per\s?cent\b", "%", t, flags=re.I)))
    errs = claim_errors(fc, t)
    flags = [] if errs else engineer.model_read_errors(text, data, client)
    if any(c in e for e in errs for c in DIFFERS):
        return "differs from the record", (errs + overstated)[:6], flags
    if errs:
        return "cannot be checked against this record", (errs + overstated)[:6], flags
    if overstated:
        return "overstates what the record can show", overstated[:6], flags
    if not checked_numbers(fc, t):
        return ("cannot be checked against this record",
                ["no number in the sentence is a count this record holds, so nothing in it was tested"], flags)
    return "consistent with the record", [], flags


def verdict_errors(text: str, check: dict) -> list[str]:
    """A finding about a checked claim must state the verdict the check gave, and only the claim's own numbers."""
    out = []
    words = VERDICT_WORDS.get(check["verdict"], ())
    if not any(w in text.lower() for w in words):
        out.append(f"the check found the claim '{check['verdict']}'; say so")
    others = [v for v, ws in VERDICT_WORDS.items() if v != check["verdict"] and any(w in text.lower() for w in ws)
              and not any(w in text.lower() for w in words)]
    if others:
        out.append(f"states '{others[0]}' but the check found '{check['verdict']}'")
    extra = numbers_in(text) - numbers_in(check["claim"])
    if extra:
        out.append(f"{', '.join(sorted(extra))} is not in the checked claim; record numbers cite their D receipt")
    return out


def program_match(city: str, name: str) -> dict:
    """The city's verdict on the program the source names, matched by its words to the registered studies (city id or
    name, any casing); 'untested' with the list of programs that have a study when none matches."""
    from . import opendata
    cid = next((c["id"] for c in opendata.load_cities() if (city or "").lower() in (c["id"], c.get("name", "").lower())),
               city)
    progs = treatments.programs(cid)
    want = set(_norm(name).split()) - {"the", "and", "of", "program", "programs", "a"}
    def score(p):
        have = set(_norm(f"{p.get('countermeasure') or ''} {p.get('label') or ''}").split())
        acro = "".join(w[0] for w in _norm(p.get("countermeasure") or "").split())
        return len(want & have) + (2 if acro and acro in want else 0)
    best = max(progs, key=lambda p: (score(p), p["status"] == "worked", p["sites"]), default=None)
    if best is None or score(best) == 0:
        return {"status": "untested", "countermeasure": name, "city": cid,
                "programs_with_studies": sorted({p["label"] for p in progs})}
    same = [p for p in progs if score(p) == score(best)]
    return max(same, key=lambda p: (p["status"] == "worked", p["sites"]))


def nearest_corner(city: str | None, lat: float, lon: float) -> tuple[dict, float] | None:
    """The city's screened intersection nearest a point, and its distance in metres (None without a saved screen)."""
    from . import citywide
    rows = [r for c, res in citywide.screened() if c == city for r in res["rows"] if r.get("lat") and not r.get("error")]
    if not rows:
        return None
    j = min(rows, key=lambda r: context.metres(lat, lon, r["lat"], r["lon"]))
    return j, context.metres(lat, lon, j["lat"], j["lon"])


SMALL_RECEIPTS = ("check_claim", "program_record")  # kept whole in results; a corner's record is rebuilt from the cache


def replay_record(case: dict) -> dict:
    """The record a finished case's investigate call built, rebuilt from the cache by the same call with the same
    address (by tool name: root_cause, test_programs, choose_fixes, who_must_act, ...)."""
    import os
    desk = Desk(case.get("city"))
    inv = next(t for t in core_tools(desk) if t.name == "investigate")
    replay, SETTINGS.replay = SETTINGS.replay, True
    pinned = os.environ.get("NML_ASOF")
    if run_asof(case):
        os.environ["NML_ASOF"] = run_asof(case)  # the window the run queried, not today's
    try:
        for s in case.get("trace") or []:
            if s.get("tool") == "investigate" and not s.get("error"):
                if "error" not in inv.fn(**{**s["args"], "draft_letter": False}):
                    break
    finally:
        SETTINGS.replay = replay
        if pinned is None:
            os.environ.pop("NML_ASOF", None)
        else:
            os.environ["NML_ASOF"] = pinned
    return {r["tool"]: r["data"] for r in desk.receipts.values() if isinstance(r["data"], dict)}


def run_asof(case: dict) -> str | None:
    """The as-of date a case's record was read at: saved with the case, or (runs before it was saved) the end of the
    window its findings state ("since 2021-11-02" is a five-year window to 2026-11-02)."""
    if case.get("asof"):
        return case["asof"]
    import datetime as dt
    text = " ".join(f.get("text", "") for f in ((case.get("final") or {}).get("findings") or []) if isinstance(f, dict))
    m = re.search(r"since ((?:19|20)\d\d-\d\d-\d\d)", text)
    if not m:
        return None
    d = dt.date.fromisoformat(m.group(1))
    return d.replace(year=d.year + context.YEARS).isoformat()


def _places(desk: Desk):
    d = engineer.Desk()
    d.places |= desk.places
    return d


def run_case(task: str, city: str, client, letter_client=None, model_check_client=None, budget_usd: float = 0.50,
             max_turns: int = 22, pages: dict | None = None, max_reads: int | None = None,
             sources_name_corner: bool = False) -> dict:
    desk = Desk(city)
    desk.pages.update(pages or {})
    desk.final = None
    space, ds_tools = dataset_tools(city, desk)
    server = [{"type": "web_search"}] + ([space, {"type": "tool_search"}] if space else [])
    t0 = time.time()
    run = run_agent(client, MODEL, INSTRUCTIONS, task, core_tools(desk, letter_client, model_check_client, client, max_reads, sources_name_corner) + ds_tools,
                    max_turns, budget_usd, effort="low", tag=f"desk {task[:40]}", escalate_after=3,
                    required=("investigate",), governor=True, server_tools=server,
                    include=("web_search_call.results",), on_response=desk.collect)
    rep = desk.report or {}
    return {"task": task, "city": city, "finished": desk.final is not None, "final": desk.final,
            "stopped": run.stopped, "turns": run.turns, "usd": round(run.usd, 4), "seconds": round(time.time() - t0, 1),
            "refusals": run.refusals, "web": desk.web,
            "trace": [{"turn": s.turn, "tool": s.tool, "args": {k: v for k, v in (s.arguments or {}).items() if k != "findings"},
                       "error": (s.result or {}).get("error") if isinstance(s.result, dict) else None,
                       "errors": (s.result or {}).get("errors") if isinstance(s.result, dict) else None} for s in run.steps],
            "receipts": {k: (v if v["tool"] in SMALL_RECEIPTS else {kk: vv for kk, vv in v.items() if kk != "data"})
                         for k, v in desk.receipts.items()},
            "corner": (rep.get("junction") or {}).get("name"), "asof": config_asof().isoformat(),
            "letter": ((rep.get("findings") or {}).get("draft_request") or {}).get("letter")}
