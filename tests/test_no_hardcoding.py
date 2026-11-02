"""No place is written into the generic product code (plan 44, section 7.1).

The forbidden list is built from the saved results, so it grows with every run: every corner name the desk and the
city plans produced, the distinctive words of those names, every source's web host, every tested program label, and
the registry's city ids and names. None may appear in the modules that must work for any city, or in the prompts and
task templates the model sees. A city reaches that code only as data (the registry) or as input."""
import glob
import inspect
import json
import re
from urllib.parse import urlparse

from nearmisslens import check, jobs, opendata, orchestrator
from nearmisslens.config import ROOT

BENCH = ROOT / "validation" / "results" / "bench"
GENERIC = [check, jobs]  # the modules that must know no city; add new generic modules here
# words that are common English or street vocabulary, not a place (each needed because a corner name contains it)
COMMON = set("""street avenue boulevard road place drive lane court parkway highway expressway square terrace way
north south east west northeast northwest southeast southwest the and of at near center park bridge hill market
main first second third fourth fifth sixth seventh eighth ninth tenth broadway plaza circle loop route state city
new old union mission gates point upper cross states post""".split())


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
