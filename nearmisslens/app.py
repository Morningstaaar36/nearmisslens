"""The copilot, live: the same page as the static site (nml pages), served with two endpoints for corners that are not
precomputed. Runs on 127.0.0.1 by default (nml app); the Modal app runs it in public mode.

    GET  /                  the page (nearmisslens/web/copilot.html, mode "live")
    GET  /data/...          the static site's files (docs/data: index, evidence, one report per corner, photos)
    POST /engineer          {"address": "..."} -> the deterministic engineer report (no model, a request-cap)
    POST /letter            {"name", "lat", "lon"} -> a drafted, number-checked request letter (Muse Spark Open)

Public mode (NML_PUBLIC=1): global daily caps on requests and model dollars (budget.DailyBudget), no illustration,
no caller identity kept, places outside the registered cities refused, errors in plain words."""
from __future__ import annotations

import json
import math
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import brief, context, engineer, letter
from .budget import DailyBudget
from .config import ROOT, SETTINGS
from .evaluate import RESULTS_DIR

WEB = ROOT / "nearmisslens" / "web"
DOCS = ROOT / "docs"
MAX_BODY = 4096
LETTER_RESERVE_USD = 0.03
ASK_RESERVE_USD = 0.05


class BadRequest(ValueError):
    pass


def parse(raw: bytes) -> dict:
    try:
        q = json.loads(raw or b"{}")
    except ValueError:
        raise BadRequest("the request body is not JSON")
    if not isinstance(q, dict):
        raise BadRequest("the request body must be a JSON object")
    return q


def address(q: dict) -> str:
    a = q.get("address")
    if not isinstance(a, str) or not 3 <= len(a.strip()) <= 160 or not a.isprintable():
        raise BadRequest("give an intersection as text, e.g. \"Delancey Street & Essex Street, Manhattan, NY\"")
    return a.strip()


def point(q: dict) -> tuple[str, float, float]:
    name, lat, lon = q.get("name"), q.get("lat"), q.get("lon")
    if not isinstance(name, str) or not 3 <= len(name) <= 160 or not name.isprintable():
        raise BadRequest("name must be the corner's name")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)):
        raise BadRequest("lat and lon must be numbers")
    if context.city_of(lat, lon) is None:
        raise BadRequest("that place is outside the cities this copy covers")
    return name, float(lat), float(lon)


def question(q: dict) -> tuple[str, str, str]:
    """(city, corner slug, question) for /ask; the city defaults to the first city with a saved screen."""
    import re
    from . import citywide
    slug, text, city = q.get("slug"), q.get("question"), q.get("city") or next(iter(citywide.cities()), None)
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", slug):
        raise BadRequest("slug must be a corner id from the list")
    if not isinstance(text, str) or not 3 <= len(text.strip()) <= 300 or not text.isprintable():
        raise BadRequest("ask a question of at most 300 characters")
    if not isinstance(city, str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", city):
        raise BadRequest("city must be a registry city id")
    return city, slug, text.strip()


def static_file(path: str):
    """A file under docs/ (never outside it), or None."""
    rel = unquote(path).lstrip("/")
    p = (DOCS / rel).resolve()
    if not p.is_relative_to(DOCS.resolve()) or not p.is_file() or "video" in p.relative_to(DOCS.resolve()).parts[:1]:
        return None
    return p


def evidence() -> dict:
    """What the causal gate found for every registered program (validation/results/bench/study_*.json), and how the
    gate fared on fake programs (T12)."""
    from . import opendata, treatments
    programs = []
    for res in treatments.results():
        for key, g in res.get("gates", {}).items():
            m = (res["runs"].get(g["primary"]) or {}).get(g["outcome"]) or {}
            pl = (res["runs"].get(g["placebos"][-1]) or {}).get(g["outcome"]) if g.get("placebos") else None
            programs.append({"city": res["city"], "city_name": (opendata.city(res["city"]) or {}).get("name", res["city"]),
                             "study": res["id"], "program": g["treatment"], "countermeasure": g.get("countermeasure"),
                             "passed": g["passed"], "reason": g["reason"], "outcome": g["outcome"],
                             "effect_pct": m.get("change_pct"), "sites": m.get("sites"),
                             "ci_pct": [round(100 * (v - 1), 1) for v in m["ci95"]] if m.get("ci95") else None,
                             "placebo_pct": pl and pl.get("change_pct"),
                             "comparison": g["primary"][len(key) + 1:].replace("_", " "),
                             "naive_pct": ((res.get("naive") or {}).get(key, {}).get(g["outcome"]) or {}).get("change_pct"),
                             "fake_rank": (g.get("fake_rank") or {}).get("rank")})
    t12 = RESULTS_DIR / "bench" / "experiment_T12.json"
    fake = json.loads(t12.read_text())["summary"] if t12.exists() else None
    return {"programs": programs, "fake_programs": fake}


def serve(port: int = 8770, open_weights: bool = True, illustrate: bool = False) -> int:
    from .meta_client import MetaClient
    if open_weights:
        from .openclient import OpenWeightsClient
        memo_client = OpenWeightsClient()
    else:
        memo_client = MetaClient(SETTINGS)
    from .pages import page
    html = page("live").encode()
    public = os.environ.get("NML_PUBLIC") == "1"
    budget = DailyBudget()

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, html, "text/html; charset=utf-8")
            if u.path in ("/copilot.js", "/copilot.css"):
                return self._send(200, (WEB / u.path[1:]).read_bytes(),
                                  "text/javascript" if u.path.endswith(".js") else "text/css")
            if u.path.startswith("/data/"):
                p = static_file(u.path)
                if p:
                    return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise BadRequest("the request is too large")
                q = parse(self.rfile.read(n))
                if path == "/engineer":
                    a = address(q)
                    if public and not budget.request():
                        return self._json(429, {"error": "today's limit for new corners is reached; the city's "
                                                         "priority corners are still open from the list"})
                    lat, lon, name = brief.geocode(a)
                    if context.city_of(lat, lon) is None:
                        raise BadRequest("that place is outside the cities this copy covers")
                    return self._json(200, engineer.investigate(engineer.Desk(), a, name, lat, lon))
                if path == "/letter":
                    name, lat, lon = point(q)
                    if public and not budget.reserve(LETTER_RESERVE_USD):
                        return self._json(429, {"error": "letter drafting is paused for today (the daily model "
                                                         "budget is used up); the facts above are still complete"})
                    spent = 0.0
                    try:
                        desk = engineer.Desk()
                        who, _ = engineer.who_must_act(desk, lat, lon, name)
                        out, _ = engineer.draft_request(desk, lat, lon, name, who, memo_client)
                        spent = out.get("usd") or 0.0
                    finally:
                        if public:
                            budget.settle(LETTER_RESERVE_USD, spent)
                    return self._json(200, {k: out.get(k) for k in ("letter", "rejected_drafts", "checker_errors", "usd")})
                if path == "/ask":
                    from . import askeng
                    city, slug, text = question(q)
                    if public and not budget.reserve(ASK_RESERVE_USD):
                        return self._json(429, {"error": "questions are paused for today (the daily model budget is "
                                                         "used up); the corner's case above is complete"})
                    spent = 0.0
                    try:
                        out = askeng.ask(city, slug, text, memo_client)
                        spent = out.get("usd") or 0.0
                    finally:
                        if public:
                            budget.settle(ASK_RESERVE_USD, spent)
                    return self._json(200, out)
                return self._json(404, {"error": "unknown endpoint"})
            except BadRequest as e:
                return self._json(400, {"error": str(e)})
            except ValueError as e:  # a place the geocoder cannot find, and similar plain failures
                return self._json(422, {"error": str(e)})
            except Exception as e:  # logged for the operator; the visitor gets a plain sentence
                print(f"{time.strftime('%H:%M:%S')} {path} failed: {type(e).__name__}: {e}", flush=True)
                return self._json(502, {"error": "a public data source did not answer; try again in a minute"})

        def log_message(self, *a):  # no request log: nothing about visitors is kept
            pass

    print(f"NearMissLens copilot: http://127.0.0.1:{port}  (letters on "
          f"{'Muse Spark Open, Baseten' if open_weights else 'the Meta API'}; Ctrl+C to stop)")
    ThreadingHTTPServer((os.environ.get("NML_HOST", "127.0.0.1"), port), H).serve_forever()
    return 0
