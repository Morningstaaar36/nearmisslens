from nearmisslens import applicability as A


def test_a_limit_counts_only_with_a_quote_from_the_record():
    text = "priorCondition: Signalized intersection with total change interval less than the ITE recommended practice."
    ans = {"kind_limit": {"present": False, "text": None, "quote": None},
           "precondition": {"present": True, "text": "timing below ITE", "quote": "total change interval less than the ITE"},
           "trend_bias": {"present": True, "text": "trend", "quote": "did not address the downward trend"}}
    g = A.gate(ans, text)
    assert g["precondition"]["present"] and not g["trend_bias"]["present"] and g["trend_bias"]["refused_quote"]


def test_the_structured_arm_reads_only_fields():
    import pandas as pd
    r = pd.Series({"areaType": "All", "priorCondition": "No RRFB", "potentialBias": ""})
    s = A.structured(r)
    assert s["kind_limit"]["present"] and not s["precondition"]["present"] and not s["trend_bias"]["present"]


def test_every_curated_record_has_a_hand_label_written_before_the_run():
    import json
    labels = json.loads(A.LABELS.read_text())
    ids = list(A.records().index)
    assert len(ids) == 25 and all(i in labels for i in ids)
    assert labels["2697"]["kind_limit"] == "school crossings" and labels["4215"]["precondition"]


def test_score_compares_arms_with_the_hand_labels():
    labels = {"1": {"kind_limit": "x", "precondition": None, "trend_bias": False},
              "2": {"kind_limit": None, "precondition": None, "trend_bias": False}}
    yes, no = {"present": True}, {"present": False}
    rows = [{"crfid": "1", "model": {"kind_limit": yes, "precondition": no, "trend_bias": no},
             "gated": {"kind_limit": {**yes, "refused_quote": False}, "precondition": {**no, "refused_quote": False},
                       "trend_bias": {**no, "refused_quote": False}},
             "structured": {"kind_limit": no, "precondition": no, "trend_bias": no}},
            {"crfid": "2", "model": {"kind_limit": yes, "precondition": no, "trend_bias": no},
             "gated": {"kind_limit": {**no, "refused_quote": True}, "precondition": {**no, "refused_quote": False},
                       "trend_bias": {**no, "refused_quote": False}},
             "structured": {"kind_limit": no, "precondition": no, "trend_bias": no}}]
    s = A.score(rows, labels)
    assert s["gated"]["all"]["accuracy"] == 1.0 and s["model"]["kind_limit"]["precision"] == 0.5
    assert s["structured"]["kind_limit"]["recall"] == 0.0 and s["refused_quotes"] == 1
