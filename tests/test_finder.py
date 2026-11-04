"""Pages found on the web are kept only when code can open them and the passage is on them (nearmisslens/finder.py)."""
from nearmisslens import finder, opendata, orchestrator

PAGE = ("The Department will install leading pedestrian intervals at Main Street and Oak Avenue in Springfield this "
        "spring, and a raised crossing at Elm Street and 3rd Avenue. " * 20)


def _setup(monkeypatch, text=PAGE):
    monkeypatch.setattr(orchestrator, "public_url", lambda u: u.startswith("https://"))
    monkeypatch.setattr(orchestrator, "text_of", lambda u, known=None: text if "good" in u else None)
    return {"name": "Springfield", "agency": "the Springfield Department of Transportation (SDOT)"}


def test_a_page_is_kept_only_with_its_passage_on_it(monkeypatch):
    city = _setup(monkeypatch)
    ok = {"url": "https://good.example/projects", "passage": "leading pedestrian intervals at Main Street and Oak Avenue"}
    assert finder.check_report(ok, city, None, set(), {ok["url"]}) is None
    assert "word for word" in finder.check_report({**ok, "passage": "a roundabout at Main Street and Oak Avenue"},
                                                  city, None, set(), {ok["url"]})
    assert "read_page" in finder.check_report(ok, city, None, set(), set())
    assert "could not be read" in finder.check_report({**ok, "url": "https://blocked.example/x"}, city, None, set(),
                                                      {"https://blocked.example/x"})
    assert "public" in finder.check_report({**ok, "url": "http://10.0.0.1/x"}, city, None, set(), {"http://10.0.0.1/x"})
    assert "twice" in finder.check_report(ok, city, None, {ok["url"]}, {ok["url"]})


def test_a_page_must_name_the_city_and_the_corner(monkeypatch):
    city = _setup(monkeypatch, PAGE.replace("Springfield", "Shelbyville"))
    ok = {"url": "https://good.example/p", "passage": "leading pedestrian intervals at Main Street and Oak Avenue"}
    assert "does not name Springfield" in finder.check_report(ok, city, None, set(), {ok["url"]})
    city = _setup(monkeypatch)
    assert finder.check_report(ok, city, "Main Street & Oak Avenue", set(), {ok["url"]}) is None
    assert "Pine" in finder.check_report(ok, city, "Main Street & Pine Road", set(), {ok["url"]})


def test_the_search_task_comes_from_the_registry_not_the_code():
    for c in opendata.load_cities():
        task = finder.TASKS["projects"].format(agency=c.get("agency") or "", city=c["name"], corner="")
        assert c["name"] in task
