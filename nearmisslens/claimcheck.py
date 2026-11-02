"""NML-Bench T20: Muse Spark reads each claim, code checks what it says (registered in validation/BENCH_PREREG.md before
any model call).

The regex checker (context.FactCheck) guesses which field a number refers to from the words near it. T18 showed where
that fails: claims that something is absent, and numbers borrowed from another field. Here Muse Spark does the reading.
For one claim and its receipt it returns every assertion the claim makes: the quoted words, the receipt field (a
dotted path), the value the claim states, and its kind (a count, a share, a change, money, or "none"); plus whether
the claim states a cause or a certainty, and any number it could not tie to a field. Code then checks each assertion
against the receipt. The claim passes only if every quote is in the claim, every field exists, every value matches
(rounding allowed; a "none" must be zero), no number is left untied, and no cause or certainty is stated.

The model never decides that a claim is true: it only says what the claim asserts, and code compares that with the
data. A model that maps a number to the wrong field is caught only if that field's value differs."""
from __future__ import annotations

import json
import re

from .cost import token_usd
from .meta_client import output_text
from .redteam import get_path, receipt_view

from .config import MODELS
MODEL = MODELS["reader"]
KINDS = ["count", "share", "change", "money", "year", "none"]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["assertions", "causal_or_certain", "untied"],
          "properties": {
              "assertions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                             "required": ["quote", "field", "value", "kind"], "properties": {
                                 "quote": {"type": "string"}, "field": {"type": "string"},
                                 "value": {"type": ["number", "null"]}, "kind": {"type": "string", "enum": KINDS}}}},
              "causal_or_certain": {"type": "boolean"},
              "untied": {"type": "array", "items": {"type": "string"}}}}
INSTRUCTIONS = (
    "You map a sentence about a street corner onto the data receipt it cites. Do not judge whether the sentence is "
    "true. List every factual assertion it makes about the data: the exact words (quote), the receipt field the "
    "assertion is about as a dotted path (for example crashes.pedestrian_killed, programs.1.sites, "
    "options.0.expected_crashes_avoided_per_year, crashes.by_year.2024), the number the sentence states for it "
    "(as written: 28 for 28%, 1325000 for $1.3 million or $1,325,000), and its kind: count, share (a percentage of "
    "crashes), change (a percentage change), money, year, or none (the sentence says there were none, zero, or "
    "never). Choose the field by what the sentence says the number is about, not by where the number appears in "
    "the receipt; if the sentence says 'killed', use a killed or deaths field even if that field is absent "
    "(write the path you would expect). Set causal_or_certain to true if the sentence says something caused "
    "crashes, that a program or fix proves, will or is certain to change crashes, or blames a party. List in untied "
    "any number in the sentence you could not tie to a field.")


def _close(stated: float, rv: float, kind: str, field: str = "") -> bool:
    """Whether the stated value is the record's value, allowing rounding and the usual scalings: a percentage may be
    rounded to a whole number (6.2% written as 6%), a count to its nearest whole, money to one decimal in millions."""
    s = abs(stated)
    pct_field = bool(re.search(r"pct|percent|share|rate|change|crf", field or ""))
    if kind == "share":  # a share of crashes: 0.277 -> 28%; never the complement, never a raw count
        cands = ([100 * rv] if 0 <= rv <= 1 else []) + ([abs(rv)] if pct_field else [])
        return any(abs(s - c) <= 0.5 for c in cands)
    if kind == "change":  # a ratio's change: theta 0.833 -> 17%; or a field that is itself a percentage change
        cands = ([100 * abs(1 - rv)] if 0 < rv <= 3 else []) + ([abs(rv)] if pct_field else [])
        return any(abs(s - c) <= 0.5 for c in cands)
    if kind == "money":
        return any(abs(s - c) <= max(0.5, 0.01 * c) if c >= 10 else abs(s - c) <= 0.051 for c in (abs(rv), abs(rv) / 1e6, abs(rv) / 1e3))
    return abs(s - abs(rv)) <= (0.5 if abs(rv) >= 1 else 0.051)  # a count, rounded to the written precision


# numbers every case states about itself rather than about the record: the confidence level, the five-year window,
# the 100 m radius; a reading that leaves them untied is not an error
from .context import CRASH_RADIUS_M, YEARS
_WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 10: "ten"}
FRAME = re.compile(rf"^\W*(95\s*%?|{_WORDS.get(YEARS, YEARS)}|{YEARS}|{CRASH_RADIUS_M}|{CRASH_RADIUS_M} ?m(eters|etres)?)\W*$", re.I)


def verify(claim: str, receipt: dict, parsed: dict, places: tuple[str, ...] = ()) -> list[str]:
    """Code's verdict on the model's reading: the reasons the claim fails (empty: it passes)."""
    from . import panel
    bad = []
    low = re.sub(r"\s+", " ", claim.lower())
    named = low
    for pl in sorted(places, key=len, reverse=True):  # street numbers in the corner's name are places, not counts
        named = named.replace(pl.lower(), " " * len(pl))
    spans = []
    for a in parsed.get("assertions") or []:
        q = re.sub(r"\s+", " ", (a.get("quote") or "").lower()).strip(" .")
        i = low.find(q) if q else -1
        if i >= 0:
            spans.append((i, i + len(q)))
    untied = [str(u) for u in parsed.get("untied") or []]
    for m in panel.NUMBER.finditer(named):  # every number must sit inside some assertion's quote
        if FRAME.match(m.group(0)) or any(a <= m.start() and m.end() <= b for a, b in spans) or m.group(0) in untied:
            continue
        if re.fullmatch(r"(19|20)\d\d|\d\d?", m.group(0).strip("-")) and re.search(r"\d{4}-\d\d-\d\d|\b(19|20)\d\d\b", named[max(0, m.start() - 8):m.end() + 8]):
            continue  # part of a date the claim gives as its window
        bad.append(f"number not covered by any assertion: {m.group(0)}")
    if parsed.get("causal_or_certain"):
        bad.append("states a cause or a certainty")
    for u in parsed.get("untied") or []:
        if not FRAME.match(str(u)):
            bad.append(f"number not tied to the record: {u}")
    if not parsed.get("assertions") and re.search(r"\d", claim):
        bad.append("numbers but no assertion")
    for a in parsed.get("assertions") or []:
        if re.sub(r"\s+", " ", (a.get("quote") or "").lower()).strip(" .") not in low:
            bad.append(f"quote not in the claim: {a.get('quote')!r}")
            continue
        rv = get_path(receipt, a.get("field") or "")
        if isinstance(rv, str) and (a.get("kind") == "year" or re.match(r"\d{4}-\d\d", rv)):
            if a.get("value") is not None and str(int(a["value"])) not in rv:
                bad.append(f"{a.get('field')} is {rv}; the claim says {a.get('value')}")
            continue  # a date: its year must match
        if isinstance(rv, bool) or (rv is not None and not isinstance(rv, (int, float))):
            bad.append(f"{a.get('field')} is not a number")
            continue
        parent = get_path(receipt, (a.get("field") or "").rsplit(".", 1)[0]) if "." in (a.get("field") or "") else receipt
        if a.get("kind") == "none":
            if rv not in (None, 0):
                bad.append(f"says none, but {a['field']} is {rv:g}")
            elif rv is None and not isinstance(parent, dict):
                bad.append(f"no field {a.get('field')} in the receipt")
            continue
        if rv is None:
            if re.search(r"killed|death|fatal|_injured$", a.get("field") or "") and a.get("value") in (0, None) \
                    and isinstance(parent, dict):
                continue  # the record lists only non-zero counts
            bad.append(f"no field {a.get('field')} in the receipt")
            continue
        if a.get("value") is None or not _close(float(a["value"]), float(rv), a.get("kind") or "count", a.get("field") or ""):
            bad.append(f"{a.get('field')} is {rv:g}; the claim says {a.get('value')}")
    return bad


def parse(client, claim: str, receipt: dict, tag: str = "") -> dict:
    body = f"Receipt: {receipt_view(receipt, 9000)}\n\nSentence: {claim}"
    request = {"model": MODEL, "instructions": INSTRUCTIONS, "schema": SCHEMA, "body": body}
    payload = {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 6000, "instructions": INSTRUCTIONS,
               "text": {"format": {"type": "json_schema", "name": "assertions", "schema": SCHEMA, "strict": True}},
               "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": body}]}]}

    def cost(resp):
        u = resp.get("usage") or {}
        return token_usd(MODEL, u.get("input_tokens", 0), u.get("output_tokens", 0)), MODEL, {
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
    resp = client.cached("claimcheck", request, lambda: client.create_response(payload), cost, 0.003,
                         f"T20 {tag}", require_text=True)
    return json.loads(output_text(resp))


def score(rows: list[dict], arm: str) -> dict:
    from .falsify import wilson
    fal = [r for r in rows if r["kind"] == "false" and r["verified"]]
    tru = [r for r in rows if r["kind"] == "true" and r["verified"]]
    k, f = sum(r[arm] for r in fal), sum(not r[arm] for r in tru)
    by = {}
    for r in fal:
        t = by.setdefault(r["error_type"], [0, 0])
        t[0] += r[arm]
        t[1] += 1
    return {"false_claims": len(fal), "accepted": k, "attack_success": round(k / max(len(fal), 1), 3),
            "attack_success_wilson95": wilson(k, len(fal)), "true_claims": len(tru), "refused": f,
            "false_refusal": round(f / max(len(tru), 1), 3), "false_refusal_wilson95": wilson(f, len(tru)),
            "by_type": {t: {"accepted": a, "attacks": n} for t, (a, n) in by.items()}}
