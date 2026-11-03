"""Program review: a list read as people keep one, every proposal reviewed, and code (not a model) ranking them into
groups and a budget plan. A fake reviewer stands in for nml review (no model, no network)."""
import json

from nearmisslens import portfolio


def _part(cm, verdict, avoided):
    return {"countermeasure": cm, "verdict": verdict,
            "proposed": {"injury_crashes_avoided_per_year": avoided} if avoided is not None else None}


def fake_review(text, city, *a, **k):
    """Each proposal's verdict is written in its text, as 'verdict=...;avoided=...;cost=...'."""
    kv = dict(x.split("=") for x in text.split("|")[1].split(";"))
    v, avoided = kv["verdict"], float(kv["avoided"]) if kv.get("avoided") else None
    cost = float(kv["cost"]) if kv.get("cost") else None
    if v == "abstain":
        return {"status": "abstained", "reason": "not found", "input": text}
    parts = [_part("A", v, avoided)] if v != "mixed" else [_part("A", "proceed", avoided), _part("B", "reconsider", None)]
    return {"status": "published", "input": text, "corner": text.split("|")[0], "verdict": v,
            "appraisal": {"verdict": v, "parts": parts, "proposed": parts[0]["proposed"], "reasons": [f"why {v}"],
                          "best_alternative": {"countermeasure": "C", "injury_crashes_avoided_per_year": 1.5}},
            "proposal": {"cost_usd": cost, "cost_covers": "this fix only" if cost else "not stated"},
            "objections": [{"id": "O1"}], "cost_usd": {"meta": 0.04, "open_weights_red_team": 0.02}, "saved": "x"}


LIST = "\n".join([
    "1. A St & B Ave|verdict=proceed;avoided=0.6;cost=100000",
    "2. C St & D Ave|verdict=proceed;avoided=0.3;cost=20000",
    "- E St & F Ave|verdict=proceed_after_site_check;avoided=0.4",
    "G St & H Ave|verdict=compare_alternative;avoided=0.2;cost=50000",
    "I St & J Ave|verdict=reconsider;cost=80000",
    "K St & L Ave|verdict=outside_evidence",
    "M St & N Ave|verdict=mixed;avoided=0.5;cost=300000",
    "O St & P Ave|verdict=abstain",
])


def test_a_list_is_read_as_lines_csv_or_json():
    assert [x["text"] for x in portfolio.read_list("1. One proposal here\n- Two proposal here\n\n")] == \
        ["One proposal here", "Two proposal here"]
    rows = portfolio.read_list("project,cost_usd\n\"Beacons at A St & B Ave\",\"$45,000\"\nIsland at C & D,\n")
    assert rows == [{"text": "Beacons at A St & B Ave", "cost_usd": 45000.0}, {"text": "Island at C & D"}]
    js = portfolio.read_list(json.dumps({"projects": [{"text": "Beacons at A & B", "cost_usd": 5}, "Island at C & D"]}))
    assert js == [{"text": "Beacons at A & B", "cost_usd": 5}, {"text": "Island at C & D"}]
    assert portfolio._proposal_text({"text": "Beacons at A & B", "cost_usd": 45000}) == \
        "Beacons at A & B (estimated cost $45,000)"


def test_code_groups_and_ranks_the_program_and_fits_a_budget(tmp_path):
    p = portfolio.run(LIST, "zz", reviewer=fake_review, budget_usd=150000, out_dir=tmp_path, workers=2)
    t = p["totals"]
    assert (t["proposals"], t["reviewed"], t["not_reviewed"]) == (8, 7, 1)
    assert (t["build"], t["site_check"], t["compare"], t["parts"], t["study"], t["reconsider"]) == (2, 1, 1, 1, 1, 1)
    # ranked by injury crashes avoided per dollar: 0.3 for $20k (15/M) before 0.6 for $100k (6/M)
    assert [x["corner"] for x in p["groups"]["build"]] == ["C St & D Ave", "A St & B Ave"]
    assert t["avoided_per_year_if_supported_built"] == round(0.6 + 0.3 + 0.4 + 0.5, 2)
    plan = p["budget_plan"]
    assert [c.split("|")[0] for c in plan["chosen"]] == ["C St & D Ave", "A St & B Ave"]  # the $300k mixed one does not fit
    assert plan["spent_usd"] == 120000 and plan["avoided_per_year"] == 0.9
    assert [c.split("|")[0] for c in plan["no_cost_given"]] == ["E St & F Ave"]
    assert t["reconsider_cost_usd"] == 80000 and t["review_cost_usd"] == 0.42
    assert p["groups"]["compare"][0]["alternative"]["countermeasure"] == "C"
    md = (tmp_path / "program.md").read_text()
    assert "Within a budget of $150,000" in md and "Not reviewed" in md and "no model compares" in md


def test_an_interrupted_program_resumes_without_paying_twice(tmp_path):
    calls = []

    def counting(text, *a, **k):
        calls.append(text)
        return fake_review(text, *a, **k)
    portfolio.run(LIST, "zz", reviewer=counting, out_dir=tmp_path)
    first = len(calls)
    portfolio.run(LIST, "zz", reviewer=counting, out_dir=tmp_path)
    assert first == 8 and len(calls) == 8  # every saved review reused


def test_a_failed_review_is_a_result_and_the_program_goes_on(tmp_path):
    def flaky(text, *a, **k):
        if text.startswith("A St"):
            raise RuntimeError("geocoder down")
        return fake_review(text, *a, **k)
    p = portfolio.run(LIST, "zz", reviewer=flaky, out_dir=tmp_path)
    assert p["totals"]["not_reviewed"] == 2 and "geocoder down" in p["not_reviewed"][0]["reason"]
