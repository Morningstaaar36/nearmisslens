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

MODEL = "muse-spark-1.3"
GEO_KINDS = ("crash", "project", "designation", "crash_detail")
INSTRUCTIONS = (
    "You work for a city's street-safety team. Given a real-world input (a news story, a statement, a resident's "
    "report, a corner or a city), find the facts, investigate the corner and check what was claimed. Use web_search "
    "to find and open the source; quote it exactly. Call investigate on the intersection to get its checked case. "
    "Load the city's open datasets with tool search when you need more records. Use check_claim on each number the "
    "source states and program_record when a source credits a safety program. Finish with: a short summary for the "
    "safety team; findings, each a plain sentence citing the receipt id it rests on (numbers exactly as the receipt "
    "has them; never 'caused', 'proves', 'will'): the injury crashes and what they have in common, the city's verdict on "
    "the relevant program, the fix the evidence supports and its evidence tier, who owns the road, and the verdict on "
    "each claim you checked; and sources, each with its URL and an exact quote from that page. "
    "If finish is refused, fix what it names.")


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def page_text(url: str) -> str:
    """A web page's visible text (cached on disk like every fetch), for the citation gate."""
    import httpx
    key = context.hashlib.sha256(url.encode()).hexdigest()[:24]
    path = context._cache_dir() / f"page_{key}.txt"
    if path.exists():
        return path.read_text()
    from .config import SETTINGS
    if SETTINGS.replay:
        return ""
    try:  # our own, honest user agent: a site that refuses automated readers is respected, and its quote is
        # published marked unverified rather than fetched another way
        with httpx.Client(headers=context.UA, timeout=30, follow_redirects=True) as c:
            r = c.get(url)
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    except Exception:
        text = ""
    text = re.sub(r"\s+", " ", text)
    path.write_text(text)
    return text


def _norm(s: str) -> str:
    """Lower case, letters and digits only, single spaces: a quote matches the page despite punctuation and quotes."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


READABLE = 1500  # characters of visible text below which a page did not load (blocked, script-only or a file)


def quote_check(quote: str, url: str) -> str:
    """'verified' (the quote is in the page), 'absent' (the page loaded and the quote is not in it) or 'unreadable'
    (the page could not be read here, so the quote is published marked unverified, never refused for that alone)."""
    text = page_text(url)
    if len(text) < READABLE:
        return "unreadable"
    q = _norm(quote)
    return "verified" if len(q) >= 12 and q in _norm(text) else "absent"


def quote_in_page(quote: str, url: str) -> bool:
    return quote_check(quote, url) == "verified"


class Desk:
    """The case being worked: receipts (id -> tool, data, query), sources, and the corner's engineer report."""

    def __init__(self):
        self.receipts: dict[str, dict] = {}
        self.report: dict | None = None
        self.web: list[dict] = []
        self.places: set[str] = set()

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


def core_tools(desk: Desk, letter_client=None, model_check_client=None, model_client=None) -> list[Tool]:
    txt, num = {"type": "string"}, {"type": "number"}

    def investigate(address: str, draft_letter: bool):
        from . import brief
        last = None
        for variant in brief.address_variants(address):  # "Bay Pkwy and Cropsey Ave" -> "Bay Parkway & Cropsey Avenue"
            try:
                rep = engineer.plan(variant, letter_client=letter_client if draft_letter else None)
                break
            except ValueError as e:
                last = e
        else:
            raise last
        desk.report = rep
        desk.places.add(rep["junction"]["name"].split(",")[0])
        ids = {}
        for r in rep["receipts"]:
            if r["tool"] in rep["findings"]:
                ids[r["tool"]] = desk.receipt(r["tool"], rep["findings"][r["tool"]])
        letter = (rep["findings"].get("draft_request") or {}).get("letter")
        return {"corner": rep["junction"]["name"], "receipts": ids, "claims": [c["text"] for c in rep["claims"]][:14],
                **({"letter": letter} if letter else {})}

    def check_claim(text: str, receipt: str):
        d = desk.receipts.get(receipt)
        if not d:
            return {"error": f"no receipt {receipt}"}
        data = d["data"]
        errs = context.FactCheck(data).text(engineer.strip_places(text, _places(desk))) + engineer.wording(text)
        errs = errs or engineer.model_read_errors(text, data, model_check_client)
        if errs and all("is not in the dossier" in e or "not covered" in e for e in errs):
            verdict = "not in the public record (cannot be checked)"  # e.g. a victim's age, the time of day
        else:
            verdict = "contradicted by the record" if errs else "consistent with the record"
        return {"verdict": verdict, "reasons": errs[:6]}

    def program_record(city: str, countermeasure: str):
        st = treatments.program_status(city, countermeasure)
        return {"receipt": desk.receipt("program_record", st), **{k: st.get(k) for k in ("status", "label", "text", "sites", "source")}}

    def finish(summary: str, findings: list[dict], sources: list[dict]):
        errors = []
        for k, f in enumerate(findings, 1):
            d = desk.receipts.get(f.get("receipt"))
            if not d:
                errors.append(f"finding {k} cites no receipt (got {f.get('receipt')!r})")
                continue
            t = engineer.strip_places(f.get("text", ""), _places(desk))
            errors += [f"finding {k}: {e}" for e in context.FactCheck(d["data"]).text(t)
                       + engineer.conditional_fix_errors(t, d["data"]) + engineer.wording(t)]
        checked = []
        for k, s in enumerate(sources, 1):
            state = quote_check(s.get("quote", ""), s.get("url", ""))
            if state == "absent":
                errors.append(f"source {k}: the quote is not in the page at {s.get('url')} (copy it exactly)")
            checked.append({**s, "quote_check": state})
        errors += [f"summary: {e}" for e in engineer.wording(summary)]
        numbered = [f for f in findings if re.search(r"\d", f.get("text", ""))]
        if len(numbered) < 3:  # a publishable case states the record's numbers, not just that a case exists
            errors.append(f"only {len(numbered)} findings give a number from the record; give at least 3 (crashes, "
                          "what they have in common, the program verdict, the fix and its evidence, the owner)")
        if not sources:
            errors.append("no source: cite the page the input came from, with an exact quote")
        if errors:
            return {"error": "refused by the publish gate", "errors": errors[:12]}
        desk.final = {"summary": summary, "findings": findings, "sources": checked}
        return {"ok": True}

    def view_photo(url: str, question: str):
        """Muse Spark looks at a photo (low effort: seeing does not improve with more thinking); code first refuses
        an unreadable or dark image (evidence or abstain). The answer is a model observation, labelled as such."""
        import cv2
        import httpx
        import numpy as np
        from . import sam_api
        from .cost import token_usd
        from .meta_client import output_text
        try:
            with httpx.Client(headers=context.UA, timeout=30, follow_redirects=True) as c:
                raw = c.get(url).content
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None or float(img.mean()) < 40:
            return {"answer": "unsure", "why": "the photo could not be read or is too dark", "receipt": desk.receipt("photo_read", {"readable": False})}
        h, w = img.shape[:2]
        if max(h, w) > 1280:
            img = cv2.resize(img, (int(w * 1280 / max(h, w)), int(h * 1280 / max(h, w))))
        schema = _obj({"shows": txt, "answer": {"type": "string", "enum": ["yes", "no", "unsure"]},
                       "who_is_at_risk": {"type": "array", "items": txt}}, ["shows", "answer", "who_is_at_risk"])
        model = "muse-spark-1.3-contributor"
        inst = ("Describe what this street photo shows in one sentence, then answer the question yes, no or unsure "
                "(unsure if the photo does not show it clearly), and list who it puts at risk.")
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
        Tool("investigate", "Build the checked case for an intersection: crashes, patterns, the city's programs, "
             "fixes by evidence, road owners; optionally a number-checked request letter.",
             _obj({"address": txt, "draft_letter": {"type": "boolean"}}, ["address", "draft_letter"]), investigate),
        Tool("check_claim", "Check one sentence (from a source or your draft) against a receipt.",
             _obj({"text": txt, "receipt": txt}, ["text", "receipt"]), check_claim),
        Tool("view_photo", "Look at a photo (e.g. from a resident's report) and answer a question about it.",
             _obj({"url": txt, "question": txt}, ["url", "question"]), view_photo),
        Tool("program_record", "What the city's own crash record says about a safety program (the causal gate).",
             _obj({"city": txt, "countermeasure": txt}, ["city", "countermeasure"]), program_record),
        Tool("finish", "Publish: summary, findings citing receipts, and sources with exact quotes.",
             _obj({"summary": txt, "findings": claim, "sources": source}, ["summary", "findings", "sources"]), finish),
    ]


def _places(desk: Desk):
    d = engineer.Desk()
    d.places |= desk.places
    return d


def run_case(task: str, city: str, client, letter_client=None, model_check_client=None, budget_usd: float = 0.40,
             max_turns: int = 16) -> dict:
    desk = Desk()
    desk.final = None
    space, ds_tools = dataset_tools(city, desk)
    server = [{"type": "web_search"}] + ([space, {"type": "tool_search"}] if space else [])
    t0 = time.time()
    run = run_agent(client, MODEL, INSTRUCTIONS, task, core_tools(desk, letter_client, model_check_client, client) + ds_tools,
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
            "receipts": {k: {kk: vv for kk, vv in v.items() if kk != "data"} for k, v in desk.receipts.items()},
            "corner": (rep.get("junction") or {}).get("name"),
            "letter": ((rep.get("findings") or {}).get("draft_request") or {}).get("letter")}
