"""The copilot, live: the same page as the static site (nml pages), served with two endpoints for corners that are not
precomputed. Runs on 127.0.0.1 by default (nml app); the Modal app runs it in public mode.

    GET  /                  the page (nearmisslens/web/copilot.html, mode "live")
    GET  /data/...          the static site's files (docs/data: index, evidence, one report per corner, photos)
    POST /engineer          {"address": "..."} -> the deterministic engineer report (no model, a request-cap), or,
                            when it takes longer than ENGINEER_WAIT_S (a corner never fetched before), {"job": id}
    GET  /engineer/<id>     {"status": "running" | "done" | "failed", "seconds", "result"?}
    POST /letter            {"name", "lat", "lon"} -> a drafted, number-checked request letter (Muse Spark Open)
    GET  /cities            the registry's cities and whether each can be checked, the server's limits and the service
                            facts the page shows (records date, today's budget left, source repository)
    GET  /health            {"ok": true, ...}: for an uptime monitor
    POST /check             {"input", "city", "kind"?, "photo"?, "address"?} -> {"job": id}: the desk on one input
    GET  /check/<id>        {"status": "running" | "done" | "failed", "seconds", "result"?}
    POST /review            {"proposal", "city"} -> {"job": id}: Before you commit, a review of a proposed project
    GET  /review/<id>       {"status": "running" | "done" | "failed", "seconds", "result"?}
    POST /portfolio         {"proposals": "one per line", "city", "budget_total"?} -> {"job": id}: a program review
    GET  /portfolio/<id>    {"status": "running" | "done" | "failed", "seconds", "result"?}

Public mode (NML_PUBLIC=1): global daily caps on requests and model dollars (budget.DailyBudget), a per-visitor
hourly limit on paid jobs (budget.VisitorLimit: a salted hash in memory only), no illustration, no caller identity kept, places outside the registered cities refused, errors in plain words."""
from __future__ import annotations

import json
import math
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import brief, context, engineer, letter
from . import __version__
from .budget import DailyBudget, VisitorLimit
from .config import ROOT, SETTINGS, asof
from .evaluate import RESULTS_DIR

WEB = ROOT / "nearmisslens" / "web"
DOCS = ROOT / "docs"
MAX_BODY = 4096
LETTER_RESERVE_USD = 0.03
ASK_RESERVE_USD = 0.05
ENGINEER_WAIT_S = 20.0  # answer in the request when it is quick; otherwise the page polls (a proxy cuts long requests)
ENGINEER_SLOTS = 3  # new corners investigated at once (no model; public map and data servers set the pace)
CHECK_BUDGET_USD = float(os.environ.get("NML_CHECK_BUDGET_USD", "0.50"))  # one desk case's Meta cap, reserved first
# the origins of the page's static copy (e.g. the GitHub Pages site), comma-separated, allowed to call the endpoints
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("NML_ALLOWED_ORIGINS", "").split(",") if o.strip()}
PROGRAM_ITEMS = int(os.environ.get("NML_PROGRAM_ITEMS", "4"))  # proposals in one program review on the server
PAID = ("/engineer", "/letter", "/check", "/review", "/portfolio", "/ask", "/find")  # each counts against the visitor's hourly limit


def repo_url() -> str:
    """Where the source and every registered test live: NML_REPO_URL (set by the Modal image), else pyproject's."""
    if os.environ.get("NML_REPO_URL"):
        return os.environ["NML_REPO_URL"]
    try:
        import tomllib
        return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["urls"]["Repository"]
    except (OSError, KeyError, ValueError):
        return ""


FIND_RESERVE_USD = 0.50  # a web search for pages ($0.10 to $0.20) and reading their projects (up to $0.20)
PROGRAM_REVIEW_USD = 0.20  # each proposal's Meta cap within a program (a review costs about $0.04); 4 reserve $1.00


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
        raise BadRequest("give an intersection as text: two street names joined by \"&\", and the city")
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
    visitors = VisitorLimit()
    started = time.time()

    def service() -> dict:
        """What the page tells a visitor about this server: records date, today's budget left, where the source is."""
        out = {"version": __version__, "records_as_of": asof().isoformat(), "repository": repo_url(), "public": public,
               "visitor_jobs_per_hour": visitors.jobs if public else None}
        if public:
            day = budget.state()
            out["budget_left_usd"] = round(max(0.0, day["usd_cap"] - day["usd"]), 2)
            out["budget_usd"] = day["usd_cap"]
        return out
    from . import check
    from .jobs import Busy, Jobs, Paused
    desk_client = MetaClient(SETTINGS)
    jobs = Jobs(lambda q: check.check(q["input"], q["city"], kind=q.get("kind"), photo=q.get("photo"),
                                      address=q.get("address"), budget_usd=CHECK_BUDGET_USD, client=desk_client,
                                      letter_client=memo_client, model_check_client=desk_client),
                budget if public else None, CHECK_BUDGET_USD)

    from . import review as reviews
    from .openclient import OpenWeightsClient
    reviewing = Jobs(lambda q: reviews.review(q["proposal"], q["city"], desk_client, memo_client, OpenWeightsClient(),
                                              budget_usd=CHECK_BUDGET_USD),
                     budget if public else None, CHECK_BUDGET_USD + reviews.RED_TEAM_BUDGET_USD,
                     SETTINGS.runs_dir / "reviews" / "jobs", busy="another review is running; try again in a few minutes")

    from . import portfolio as programs

    def program(q: dict) -> dict:
        p = programs.run(q["proposals"], q["city"], desk_client, None, OpenWeightsClient(),
                         budget_usd=q.get("budget_total"), per_review_usd=PROGRAM_REVIEW_USD,
                         title=f"Program review: {len(programs.read_list(q['proposals']))} proposals")
        return {**p, "markdown": programs.portfolio_md(p, p["title"]),
                "cost_usd": {"reviews": p["totals"]["review_cost_usd"]}}
    programming = Jobs(program, budget if public else None,
                       PROGRAM_ITEMS * (PROGRAM_REVIEW_USD + reviews.RED_TEAM_BUDGET_USD),
                       SETTINGS.runs_dir / "programs" / "jobs", busy="another program review is running; try again later")

    from . import finder

    def finding(q: dict) -> dict:
        r = finder.find(q["city"], desk_client, corner=q["corner"]) if q.get("corner") else \
            finder.find_projects(q["city"], desk_client)
        return {**r, "cost_usd": {"find": r["usd"]}}
    finds = Jobs(finding, budget if public else None, FIND_RESERVE_USD, SETTINGS.runs_dir / "finds" / "jobs",
                 busy="another web search is running; try again in a minute")

    def investigate(q: dict) -> dict:
        lat, lon, name = brief.geocode(q["address"])
        if context.city_of(lat, lon) is None:
            raise BadRequest("that place is outside the cities this copy covers")
        return engineer.investigate(engineer.Desk(), q["address"], name, lat, lon)

    corners = Jobs(investigate, None, 0.0, SETTINGS.runs_dir / "engineer" / "jobs", slots=ENGINEER_SLOTS,
                   busy="the server is investigating other new corners; try again in a minute", plain=(ValueError,))

    class H(BaseHTTPRequestHandler):
        def _cors(self) -> bool:
            """The static copy of the page (another origin, listed in NML_ALLOWED_ORIGINS) may call the endpoints."""
            origin = self.headers.get("Origin")
            if origin and origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                return True
            return False

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")  # map tiles need the origin
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _visitor(self) -> str:
            """The caller's address for the hourly limit only: the proxy appends the real one last."""
            fwd = [a.strip() for a in (self.headers.get("X-Forwarded-For") or "").split(",") if a.strip()]
            return fwd[-1] if fwd else self.client_address[0]

        def do_OPTIONS(self):  # a browser's preflight before the static page posts JSON here
            self.send_response(204 if self.headers.get("Origin") in ALLOWED_ORIGINS else 403)
            if self._cors():
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, html, "text/html; charset=utf-8")
            if u.path in ("/copilot.js", "/copilot.css"):
                return self._send(200, (WEB / u.path[1:]).read_bytes(),
                                  "text/javascript" if u.path.endswith(".js") else "text/css")
            if u.path == "/cities":
                return self._json(200, {"cities": check.cities(), "limits": {"program_items": PROGRAM_ITEMS},
                                        "service": service()})
            if u.path == "/health":
                return self._json(200, {"ok": True, "uptime_s": round(time.time() - started), **service()})
            if u.path.startswith(("/check/", "/engineer/", "/review/", "/portfolio/", "/find/")):
                rec = {"/check/": jobs, "/engineer/": corners, "/review/": reviewing,
                       "/portfolio/": programming, "/find/": finds}[u.path[:u.path.index("/", 1) + 1]] \
                    .status(u.path.rsplit("/", 1)[1])
                return self._json(200, rec) if rec else self._json(404, {"error": "no such job (kept 24 hours)"})
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
                if public and path in PAID:
                    ok, wait = visitors.allow(self._visitor())
                    if not ok:
                        return self._json(429, {"error": f"you have started {visitors.jobs} jobs in the last hour, "
                                                         f"the limit for one visitor; try again in "
                                                         f"{max(1, round(wait / 60))} minutes"})
                if path == "/engineer":
                    a = address(q)
                    if public and not budget.request():
                        return self._json(429, {"error": "today's limit for new corners is reached; the city's "
                                                         "priority corners are still open from the list"})
                    try:
                        job = corners.submit({"address": a})
                    except Busy as e:
                        return self._json(409, {"error": str(e)})
                    rec = corners.wait(job, ENGINEER_WAIT_S)
                    if rec is None:
                        return self._json(202, {"job": job})
                    if rec["status"] == "failed":
                        return self._json(422 if rec.get("plain") else 502, {"error": rec["error"]})
                    return self._json(200, rec["result"])
                if path == "/letter":
                    name, lat, lon = point(q)
                    if public and not budget.reserve(LETTER_RESERVE_USD):
                        return self._json(429, {"error": "letter drafting is paused for today (the daily model "
                                                         "budget is used up); the facts above are still complete"})
                    spent = 0.0
                    try:
                        desk = engineer.Desk()  # the corner's own crashes from the first read, as in its case
                        desk.corners[(round(lat, 6), round(lon, 6))] = name.split(",")[0]
                        who, _ = engineer.who_must_act(desk, lat, lon, name)
                        out, _ = engineer.draft_request(desk, lat, lon, name, who, memo_client)
                        spent = out.get("usd") or 0.0
                    finally:
                        if public:
                            budget.settle(LETTER_RESERVE_USD, spent)
                    return self._json(200, {k: out.get(k) for k in ("letter", "rejected_drafts", "checker_errors", "usd")})
                if path == "/check":
                    q = {k: (q.get(k) or None) for k in ("input", "city", "kind", "photo", "address")}
                    if not all(isinstance(v, (str, type(None))) for v in q.values()):
                        raise BadRequest("every field must be text")
                    try:
                        check.validate(q["input"] or "", q["city"] or "", q["kind"], q["photo"])
                    except LookupError as e:
                        return self._json(422, {"error": str(e)})
                    try:
                        return self._json(202, {"job": jobs.submit(q)})
                    except Busy as e:
                        return self._json(409, {"error": str(e)})
                    except Paused as e:
                        return self._json(429, {"error": str(e)})
                if path == "/review":
                    q = {k: (q.get(k) or None) for k in ("proposal", "city")}
                    if not all(isinstance(v, str) for v in q.values()):
                        raise BadRequest("give the proposal and the city as text")
                    if len(q["proposal"]) > reviews.MAX_INPUT or len(q["proposal"].strip()) < 10:
                        raise BadRequest(f"describe the project in 10 to {reviews.MAX_INPUT} characters")
                    if check.supported(q["city"])[0] is None:
                        return self._json(422, {"error": check.supported(q["city"])[1]})
                    try:
                        return self._json(202, {"job": reviewing.submit(q)})
                    except Busy as e:
                        return self._json(409, {"error": str(e)})
                    except Paused as e:
                        return self._json(429, {"error": str(e)})
                if path == "/portfolio":
                    text, city = q.get("proposals"), q.get("city")
                    if not isinstance(text, str) or not isinstance(city, str):
                        raise BadRequest("give the proposals (one per line) and the city as text")
                    if len(text) > PROGRAM_ITEMS * reviews.MAX_INPUT:
                        raise BadRequest("the list is too long")
                    items = programs.read_list(text)
                    if not 2 <= len(items) <= PROGRAM_ITEMS or any(len(x["text"]) > reviews.MAX_INPUT for x in items):
                        raise BadRequest(f"give 2 to {PROGRAM_ITEMS} proposals, one per line (the command line "
                                         f"takes up to {programs.MAX_ITEMS})")
                    total = q.get("budget_total")
                    if total is not None and (not isinstance(total, (int, float)) or not 0 < total < 1e10):
                        raise BadRequest("the budget is a number of dollars")
                    if check.supported(city)[0] is None:
                        return self._json(422, {"error": check.supported(city)[1]})
                    try:
                        return self._json(202, {"job": programming.submit({"proposals": text, "city": city,
                                                                           "budget_total": total})})
                    except Busy as e:
                        return self._json(409, {"error": str(e)})
                    except Paused as e:
                        return self._json(429, {"error": str(e)})
                if path == "/find":
                    city, corner = q.get("city"), q.get("corner") or None
                    if not isinstance(city, str) or not isinstance(corner, (str, type(None))):
                        raise BadRequest("give the city, and the corner if any, as text")
                    if corner is not None and not (5 <= len(corner) <= 120 and "&" in corner):
                        raise BadRequest("name the corner as 'Street A & Street B'")
                    if check.supported(city)[0] is None:
                        return self._json(422, {"error": check.supported(city)[1]})
                    try:
                        return self._json(202, {"job": finds.submit({"city": city, "corner": corner})})
                    except Busy as e:
                        return self._json(409, {"error": str(e)})
                    except Paused as e:
                        return self._json(429, {"error": str(e)})
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
