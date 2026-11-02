"""NML-Bench T19: Muse Spark reads the study behind each crash-reduction factor and says where it applies
(registered in validation/BENCH_PREREG.md before any model call).

A CMF holds for sites like the ones it was measured at. The CMF Clearinghouse record says what those were, partly in
structured fields (area type, traffic control) and partly in prose (prior condition, comments, the abstract, a bias
note). For each curated record the model returns three things, each with a verbatim quote from the record:
- kind_limit: the kinds of site studied, when narrower than an urban signalized or stop-controlled corner;
- precondition: a condition at the study sites before treatment that public data cannot show for a corner;
- trend_bias: whether the record notes a trend or bias the study did not remove.
Code accepts an answer only if its quote is in the record text; an answer with a quote that is not there is refused
and counts as "no limit". The answers are scored against hand labels written before the run
(validation/experiments/T19_hand_labels.json), next to a no-model arm that reads only the structured fields."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from . import countermeasures as cm
from .config import ROOT
from .cost import token_usd
from .meta_client import output_text

from .config import MODELS
MODEL = MODELS["reader"]
FIELDS = ("kind_limit", "precondition", "trend_bias")
TEXT_FIELDS = ("cmName", "cmDesc", "priorCondition", "areaType", "trafficControl", "crashType", "crashSeverityKABCO",
               "intersecType", "roadwayType", "comments", "potentialBias", "title", "abstract")
LABELS = ROOT / "validation" / "experiments" / "T19_hand_labels.json"
_item = {"type": "object", "additionalProperties": False, "required": ["present", "text", "quote"],
         "properties": {"present": {"type": "boolean"}, "text": {"type": ["string", "null"]},
                        "quote": {"type": ["string", "null"]}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": list(FIELDS),
          "properties": {f: _item for f in FIELDS}}
INSTRUCTIONS = (
    "You read one record from the FHWA CMF Clearinghouse: a crash modification factor and the study behind it. A "
    "city engineer wants to apply it at a busy urban intersection. Say, from this record only: kind_limit: were the "
    "study sites a narrower kind of place than an urban signalized or stop-controlled intersection (for example "
    "school crossings, rural or suburban roads, mid-block crossings, single-lane roundabouts)? Do not count the "
    "traffic control type or the crash type, which are checked elsewhere. precondition: did the study sites share a "
    "condition before treatment that public crash and map data cannot show for a given corner (for example a signal "
    "timing below a standard, no street lighting, a lighting level)? Do not count 'the treatment was absent before'. "
    "trend_bias: does the record say the study did not account for a trend or another bias? For each, give present, "
    "a short plain description, and a quote copied exactly from the record that shows it (null when not present).")


def records(ids: list[str] | None = None) -> pd.DataFrame:
    raw = pd.read_csv(cm.ALLOWED_PATH, encoding="latin-1", dtype=str, keep_default_na=False)
    ids = ids or [e["crfid"] for i in cm.psc_items() for e in i.get("cmf_allow", [])]
    return raw[raw["crfid"].isin(ids)].drop_duplicates("crfid").set_index("crfid").loc[ids]


def record_text(r: pd.Series) -> str:
    parts = []
    for f in TEXT_FIELDS:
        v = str(r.get(f, "") or "").strip()
        if v and v != "\\N":
            parts.append(f"{f}: {v[:2500] if f == 'abstract' else v}")
    return "\n".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip(" .\"'")


def quoted(quote: str | None, text: str) -> bool:
    """The quote appears in the record (case and spacing ignored), and is long enough to mean something."""
    q = _norm(quote or "")
    return len(q) >= 8 and q in _norm(text)


def gate(answer: dict, text: str) -> dict:
    """The model's answer with every limit whose quote is not in the record turned off (and counted)."""
    out = {}
    for f in FIELDS:
        a = answer.get(f) or {}
        ok = bool(a.get("present")) and quoted(a.get("quote"), text)
        out[f] = {"present": ok, "text": a.get("text") if ok else None, "quote": a.get("quote") if ok else None,
                  "refused_quote": bool(a.get("present")) and not ok}
    return out


def structured(r: pd.Series) -> dict:
    """The no-model arm: only the structured fields. A narrower kind of site when the area type is not urban; a
    precondition when the prior-condition field names something other than the treatment's absence; a trend or bias
    note when the bias field is filled and does not say the biases were handled."""
    area = str(r.get("areaType") or "")
    prior = str(r.get("priorCondition") or "").strip()
    bias = str(r.get("potentialBias") or "").strip()
    absent = re.search(r"\b(no|without|not|absence)\b", prior, re.I) and len(prior.split()) <= 6
    return {"kind_limit": {"present": bool(area) and area != "\\N" and "urban" not in area.lower()},
            "precondition": {"present": bool(prior) and prior != "\\N" and not absent},
            "trend_bias": {"present": bool(bias) and bias != "\\N" and not re.search(r"properly accounts|accounts? for",
                                                                                      bias, re.I)}}


def ask(client, crfid: str, text: str) -> dict:
    request = {"model": MODEL, "instructions": INSTRUCTIONS, "schema": SCHEMA, "record": text}
    payload = {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 8000, "instructions": INSTRUCTIONS,
               "text": {"format": {"type": "json_schema", "name": "applicability", "schema": SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
    resp = client.cached("applicability", request, lambda: client.create_response(payload), cost, 0.005,
                         f"T19 CMF {crfid}", require_text=True)
    return json.loads(output_text(resp))


def score(rows: list[dict], labels: dict) -> dict:
    """Agreement with the hand labels per arm and field: accuracy, and recall/precision of 'there is a limit'."""
    out = {}
    for arm in ("model", "gated", "structured"):
        per = {}
        for f in FIELDS:
            truth = [bool(labels[r["crfid"]][f]) for r in rows]
            pred = [bool(r[arm][f]["present"]) for r in rows]
            tp = sum(t and p for t, p in zip(truth, pred))
            per[f] = {"accuracy": round(sum(t == p for t, p in zip(truth, pred)) / len(rows), 3),
                      "recall": round(tp / max(sum(truth), 1), 3), "precision": round(tp / max(sum(pred), 1), 3)}
        allp = [(bool(labels[r["crfid"]][f]), bool(r[arm][f]["present"])) for r in rows for f in FIELDS]
        per["all"] = {"accuracy": round(sum(t == p for t, p in allp) / len(allp), 3)}
        out[arm] = per
    out["refused_quotes"] = sum(r["gated"][f]["refused_quote"] for r in rows for f in FIELDS)
    return out


def run(client, ids: list[str] | None = None) -> dict:
    labels = json.loads(LABELS.read_text())
    rows = []
    for crfid, r in records(ids).iterrows():
        text = record_text(r)
        ans = ask(client, crfid, text)
        rows.append({"crfid": crfid, "name": r["cmName"], "model": {f: {"present": bool((ans.get(f) or {}).get("present")),
                                                                        **(ans.get(f) or {})} for f in FIELDS},
                     "gated": gate(ans, text), "structured": structured(r), "hand": labels.get(crfid)})
    return {"id": "T19", "registered": "validation/BENCH_PREREG.md, T19", "model": MODEL,
            "score": score(rows, labels), "rows": rows}
