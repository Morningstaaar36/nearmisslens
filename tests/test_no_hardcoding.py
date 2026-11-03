"""No place is written into the generic product code (plan 44, section 7.1).

The forbidden list is built from the saved results, so it grows with every run: every corner name the desk and the
city plans produced, the distinctive words of those names, every source's web host, every tested program label, and
the registry's city ids and names. None may appear in the modules that must work for any city, or in the prompts and
task templates the model sees. A city reaches that code only as data (the registry) or as input."""
import ast
import glob
import importlib
import inspect
import io
import json
import pkgutil
import re
import tokenize
from urllib.parse import urlparse

import nearmisslens
from nearmisslens import check, jobs, opendata, orchestrator, review
from nearmisslens.config import ROOT

BENCH = ROOT / "validation" / "results" / "bench"
GENERIC = [check, jobs, review]  # the modules that must know no city; add new generic modules here
# words that are common English or street vocabulary, not a place (each needed because a corner name contains it)
COMMON = set("""street avenue boulevard road place drive lane court parkway highway expressway square terrace way
north south east west northeast northwest southeast southwest the and of at near center park bridge hill market
main first second third fourth fifth sixth seventh eighth ninth tenth broadway plaza circle loop route state city
new old union mission gates point upper cross states post approach roadway wheeler county view white district
forest gate hook treat green fresh clean central centre inner island concourse expwy turnpike fell""".split())
# modules that are about one registered study, a saved example or the retired drone-video pipeline, by design; each
# names the place its study is about. Every other module is product code and must reach a city only through data.
STUDIES = {"fusion": "T10, residents' near-miss reports in Washington DC",
           "falsify": "T14, the calibrated gate on the New York and Seattle LPI studies",
           "demo_copilot": "the demo video's script over saved results",
           "selftest": "the offline self-test, which replays one saved corner",
           "glimmer_modal": "the drone-video pipeline's model server (a shell flag, -sf)",
           "tracks": "the drone-video pipeline's tracker (a variable, sf)",
           "bench": "writes BENCH.md, the report of every registered study, each about the city it was run in"}
# single words allowed in one module's code, with the reason
ALLOWED = {"complaints": {"la": "Spanish phrasing (girando a la izquierda)"},
           "cli": {"community": "the --letter help names the offices (council member, community board)",
                   "board": "the same help text"},
           "brief": {"junior": "the abbreviation Jr in street names, not a place",
                     "ramp": "a roadway tag in crash records (a ramp of a street), not a place"}}


def forbidden() -> set[str]:
    names, hosts, progs = set(), set(), set()
    for f in glob.glob(str(BENCH / "experiment_T21*.json")) + [str(BENCH / "experiment_T24.json")]:
        for c in json.loads(open(f).read()).get("cases", []):
            if c.get("corner"):
                names.add(c["corner"])
            for s in (c.get("final") or {}).get("sources") or []:
                if urlparse(s.get("url", "")).hostname:
                    hosts.add(urlparse(s["url"]).hostname.removeprefix("www."))
    for f in glob.glob(str(BENCH / "plan_*.json")):
        p = json.loads(open(f).read())
        names |= {c["name"] for c in p.get("corners", [])}
        progs |= {k for k in (p.get("summary") or {}).get("repeat_risk_corners", {})}
    out = {n.lower() for n in names} | hosts | {p.lower() for p in progs}
    out |= {w for n in names for w in re.findall(r"[a-z]{4,}", n.lower()) if w not in COMMON}
    for c in opendata.load_cities():
        out |= {c["id"].lower(), c["name"].lower(), *(a.lower() for a in c.get("aliases", []))}
    return out


def _hits(text: str, words: set[str]) -> list[str]:
    low = text.lower()
    return sorted(w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low))


def test_the_forbidden_list_is_built_from_real_results():
    f = forbidden()
    assert len(f) > 300 and "nyc" in f and any("." in w for w in f)  # corner words, ids and web hosts are all in it


def test_generic_modules_name_no_place():
    words = forbidden()
    for m in GENERIC:
        assert _hits(inspect.getsource(m), words) == [], m.__name__


def test_prompts_and_task_templates_name_no_place():
    words = forbidden()
    assert _hits(orchestrator.INSTRUCTIONS, words) == []
    for kind in check.KINDS:  # with an invented city: whatever the template adds must not be a real place
        task = check.task_for("INPUT", "Zedburg", kind, photo="https://example.org/p.jpg", address="1st & Main")
        assert _hits(task, words) == [], kind


def test_generic_modules_never_branch_on_a_city():
    for m in GENERIC:
        src = inspect.getsource(m)
        assert not re.search(r"city\s*==|city\s+in\s*\(|city\s+in\s*\[", src), m.__name__


def _code_only(src: str) -> str:
    """The module's code without comments and docstrings: worked examples there are documentation, not logic."""
    docs = set()
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)):
            docs.add((n.body[0].lineno, n.body[0].end_lineno))
    return " ".join(t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
                    if t.type != tokenize.COMMENT
                    and not (t.type == tokenize.STRING and any(a <= t.start[0] <= b for a, b in docs)))


def test_no_product_module_names_a_place_in_its_code():
    words, found = forbidden(), {}
    for m in pkgutil.iter_modules(nearmisslens.__path__):
        if m.name in STUDIES:
            continue
        hits = _hits(_code_only(inspect.getsource(importlib.import_module(f"nearmisslens.{m.name}"))),
                     words - set(ALLOWED.get(m.name, {})))
        if hits:
            found[m.name] = hits
    assert found == {}


def test_every_exempt_module_exists_and_says_why():
    names = {m.name for m in pkgutil.iter_modules(nearmisslens.__path__)}
    assert set(STUDIES) <= names and all(STUDIES.values())


def test_the_page_names_no_place():
    """The page (script and template) is the same for every city: its hints and filters name no place."""
    words = forbidden() - COMMON - {"marks"}  # "marks" is a verb in a legend ("Yellow marks a pattern")
    for f in ("nearmisslens/web/copilot.js", "nearmisslens/web/copilot.html"):
        src = (ROOT / f).read_text()
        assert _hits(re.sub(r"//[^\n]*", "", src), words) == [], f
