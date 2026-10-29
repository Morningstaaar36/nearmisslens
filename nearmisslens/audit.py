"""Site audit: conflicts, hotspots and countermeasures from road-user states, written as a memo with every number traced
to the data. Track ids are anonymous and per clip."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import conflicts, countermeasures, movements, risk

CELL_M = 15.0
PET_SERIOUS_S = 1.5
MIN_HOTSPOT_EVENTS = 2
EXAMPLES = 5
SIGNAL_NAMES = {"G": "green", "y": "yellow", "r": "red"}
CONFLICT_COLUMNS = ["measure", "value", "type", "id_1", "id_2", "cls_1", "cls_2", "t", "x", "y"]


def pet_type(angle: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(angle, float) > 85.0, "crossing", "turning")


def conflict_table(states: pd.DataFrame, pet_max_s: float = PET_SERIOUS_S) -> pd.DataFrame:
    """One row per interacting pair: the PET encounter when there is one (headline measure), otherwise the TTC event."""
    ttc = conflicts.ttc_events(states)
    rows = []
    if not ttc.empty:
        ttc = risk.event_locations(ttc, states)
        rows.append(pd.DataFrame({"measure": "TTC", "value": ttc["min_ttc"], "type": ttc["type"], "id_1": ttc["id_1"],
                                  "id_2": ttc["id_2"], "cls_1": ttc["cls_1"], "cls_2": ttc["cls_2"],
                                  "t": ttc["t_min_ttc"], "x": ttc["x"], "y": ttc["y"]}))
    pet = conflicts.pet_events(states)
    pet = pet[pet["pet"] <= pet_max_s]
    if not pet.empty:
        rows.append(pd.DataFrame({"measure": "PET", "value": pet["pet"], "type": pet_type(pet["angle"]),
                                  "id_1": pet["id_1"], "id_2": pet["id_2"], "cls_1": pet["cls_1"], "cls_2": pet["cls_2"],
                                  "t": pet["t_second_entry"], "x": pet["x"], "y": pet["y"]}))
    if not rows:
        return pd.DataFrame(columns=CONFLICT_COLUMNS)
    table = pd.concat(rows, ignore_index=True).dropna(subset=["x", "y"])
    table["pair"] = [tuple(sorted((str(a), str(b)))) for a, b in zip(table["id_1"], table["id_2"])]
    table["ttc_row"] = table["measure"] != "PET"
    table = table.sort_values(["ttc_row", "value"]).drop_duplicates("pair")
    return table[CONFLICT_COLUMNS].reset_index(drop=True)


def _pair(r) -> tuple[str, str]:
    return tuple(sorted((r.cls_1, r.cls_2)))


def evidence(events: pd.DataFrame, routes: pd.DataFrame, signals: pd.DataFrame | None) -> dict:
    """Movements, approach arms and signal states on entry of the non-pedestrian users in a set of conflicts."""
    ids = set(events["id_1"]) | set(events["id_2"])
    r = routes[routes["id"].isin(ids) & (routes["cls"] != "pedestrian")]
    moves = Counter(r["movement"])
    entry = Counter()
    if signals is not None and len(signals):
        entry = Counter(s for s in (movements.entry_signal(signals, x) for x in r.itertuples()) if s)
    shown = set()
    if moves["left"] or moves["right"] or moves["u_turn"]:
        shown.add("a turning movement")
    if moves["left"] or moves["u_turn"]:
        shown.add("a left-turn movement")
    if entry["y"] or entry["r"]:
        shown.add("an entry on yellow or red")
    approaches = Counter(a for a in r["entry_arm"] if a in movements.ARMS)
    return {"movements": dict(moves), "approaches": dict(approaches), "entry_signal": dict(entry), "shows": sorted(shown),
            "main_movement": moves.most_common(1)[0][0] if moves else "unknown"}


def audit(states: pd.DataFrame, cmf: pd.DataFrame, *, signals: pd.DataFrame | None, control: str | None,
          right_turn_signalised: bool, conditions: frozenset[str] = frozenset(), cell_m: float = CELL_M,
          top: int = 3) -> dict:
    """Rank cells by the lower 95% bound of conflicts per 1,000 road users, then match countermeasures to each
    cell's dominant conflict, keeping those whose condition the conflicts show and that pass the site checks.
    conditions adds site facts established elsewhere (for example "nighttime")."""
    table = conflict_table(states)
    route_table = movements.routes(states)
    users = states.groupby("id")["cls"].first().value_counts().to_dict()
    duration_s = float(states["t"].max() - states["t"].min()) if len(states) else 0.0
    hot = risk.hotspots(table, states, cell_m=cell_m, min_events=MIN_HOTSPOT_EVENTS)
    hot = hot.sort_values(["ci_low", "events"], ascending=False).head(top).reset_index(drop=True)
    findings = []
    for k, h in hot.iterrows():
        in_cell = table[(np.floor(table["x"] / cell_m) == np.floor(h["cx"] / cell_m))
                        & (np.floor(table["y"] / cell_m) == np.floor(h["cy"] / cell_m))]
        groups = Counter((_pair(r), r.type) for r in in_cell.itertuples())
        (pair, ctype), n = groups.most_common(1)[0]
        dominant = in_cell[[(_pair(r), r.type) == (pair, ctype) for r in in_cell.itertuples()]]
        ev = evidence(dominant, route_table, signals)
        cands, rejected = countermeasures.candidates(cmf, pair, ctype, control=control,
                                                     conditions=conditions | set(ev["shows"]))
        kept = []
        for c in cands:
            ok, why = countermeasures.site_check(c, ev["main_movement"], right_turn_signalised)
            if ok:
                kept.append(c)
            else:
                rejected.append({"psc": c.psc, "crfid": c.crfid, "reason": why})
        findings.append({
            "rank": k + 1, "x": round(float(h["cx"]), 1), "y": round(float(h["cy"]), 1), "cell_m": cell_m,
            "events": int(h["events"]), "users": int(h["users"]),
            "rate_per_1000": round(float(h["rate_per_1000"]), 1),
            "ci95": [round(float(h["ci_low"]), 1), round(float(h["ci_high"]), 1)],
            "by_measure": in_cell["measure"].value_counts().to_dict(),
            "examples": [{"measure": r.measure, "value": round(float(r.value), 2), "t": round(float(r.t), 1),
                          "id_1": str(r.id_1), "id_2": str(r.id_2), "cls_1": r.cls_1, "cls_2": r.cls_2, "type": r.type}
                         for r in dominant.sort_values("value").head(EXAMPLES).itertuples()],
            "dominant": {"pair": list(pair), "type": ctype, "events": int(n),
                         "min_pet_s": _min(dominant, "PET"), "min_ttc_s": _min(dominant, "TTC"), **ev},
            "countermeasures": [c.__dict__ for c in kept],
            "rejected": rejected,
        })
    return {
        "observed_s": round(duration_s, 1), "users": {str(k): int(v) for k, v in users.items()},
        "control": control or "unknown", "right_turn_signalised": right_turn_signalised,
        "conflicts": {"total": int(len(table)), "by_measure": table["measure"].value_counts().to_dict(),
                      "by_type": table["type"].value_counts().to_dict()},
        "thresholds": {"pet_s": PET_SERIOUS_S, "ttc_s": conflicts.TTC_MAX_S, "cell_m": cell_m,
                       "min_hotspot_events": MIN_HOTSPOT_EVENTS},
        "findings": findings,
    }


def _min(events: pd.DataFrame, measure: str) -> float | None:
    v = events.loc[events["measure"] == measure, "value"]
    return round(float(v.min()), 2) if len(v) else None


def memo(facts: dict, title: str, source: str) -> str:
    c = facts["conflicts"]
    users = ", ".join(f"{n} {k.replace('_', '-')}s" for k, n in sorted(facts["users"].items(), key=lambda kv: -kv[1]))
    th = facts["thresholds"]
    lines = [f"# Road safety audit: {title}", "",
             f"Source: {source}. Observed {facts['observed_s'] / 60:.1f} min; {users}. "
             f"Traffic control: {facts['control']}; right turns signal-controlled: {'yes' if facts['right_turn_signalised'] else 'no'}.", "",
             f"Conflicts: {c['total']} interacting pairs with PET ≤ {th['pet_s']} s or TTC ≤ {th['ttc_s']} s "
             f"({', '.join(f'{v} {k}' for k, v in c['by_measure'].items())}). Each pair is counted once, by PET when it has one.", "",
             f"Hotspots are {th['cell_m']:.0f} m cells ranked by the lower bound of the exact Poisson 95% interval on conflicts per "
             f"1,000 road users through the cell (at least {th['min_hotspot_events']} conflicts). These are surrogate measures "
             "from a short observation, not crash frequencies.", ""]
    if not facts["findings"]:
        lines.append("No cell reached the hotspot threshold.")
    for f in facts["findings"]:
        d = f["dominant"]
        sev = "; ".join(s for s in (f"min PET {d['min_pet_s']} s" if d["min_pet_s"] is not None else "",
                                     f"min TTC {d['min_ttc_s']} s" if d["min_ttc_s"] is not None else "") if s)
        mv = "; movements " + ", ".join(f"{v} {k.replace('_', '-')}" for k, v in d["movements"].items()) if d["movements"] else ""
        if d["entry_signal"]:
            mv += "; signal on entry " + ", ".join(f"{v} {SIGNAL_NAMES.get(k, k)}" for k, v in d["entry_signal"].items())
        lines += [f"## Hotspot {f['rank']} at ({f['x']}, {f['y']}) m", "",
                  f"{f['events']} conflicts among {f['users']} road users: {f['rate_per_1000']} per 1,000 "
                  f"(95% CI {f['ci95'][0]}–{f['ci95'][1]}). Dominant: {d['events']} {d['type'].replace('_', '-')} "
                  f"{' – '.join(p.replace('_', '-') for p in d['pair'])} conflicts ({sev}{mv}).", ""]
        if f.get("verification"):
            v = f["verification"]
            lines += [f"Muse Spark reviewed the video of the {v['reviewed']} most severe of these: {v['real']} judged real "
                      f"conflicts, {v['reviewed'] - v['real']} not ({v['evasive']} with visible braking or swerving).", ""]
        if f.get("illustration"):
            il = f["illustration"]
            verdict = "found" if il["check_passed"] else "not found"
            lines += [f"Illustration: {il['countermeasure']} ({Path(il['image']).name}). SAM 3.1 check for "
                      f"'{il['check_concept']}' in the hotspot: {verdict} (covered share {il['area_before']:.3f} before, "
                      f"{il['area_after']:.3f} after). AI-generated; not an engineering design.", ""]
        if f["countermeasures"]:
            lines += ["| FHWA Proven Safety Countermeasure | CMF Clearinghouse ID | CMF | Crash reduction | Rating | Crash type | Note |",
                      "|---|---|---|---|---|---|---|"]
            for m in f["countermeasures"]:
                lines.append(f"| {m['psc']} | {m['crfid']} | {m['cmf']:.2f} | {m['crf_pct']:.0f}% | {m['stars']} | "
                             f"{m['crash_type']} | {m['note']} |")
        else:
            lines.append("No FHWA Proven Safety Countermeasure has a crash-reducing CMF for this conflict at this site.")
        if f["rejected"]:
            lines += ["", "Considered and rejected:", ""]
            lines += [f"- {r}" for r in _rejection_lines(f["rejected"])]
        lines.append("")
    lines += ["CMF values are from the FHWA CMF Clearinghouse; a CMF below 1 means fewer expected crashes. "
              "Road users are anonymous track ids within this clip; no person is identified."]
    return "\n".join(lines) + "\n"


def _rejection_lines(rejected: list[dict]) -> list[str]:
    """One line per countermeasure and reason; CMFs rejected for the same kind of reason are listed together."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for r in rejected:
        kind = "no reduction" if "no reduction" in r["reason"] else r["reason"]
        grouped.setdefault((r["psc"], kind), []).append(r.get("crfid", ""))
    out = []
    for (psc, kind), ids in grouped.items():
        ids = [i for i in ids if i]
        if kind == "no reduction":
            out.append(f"{psc}: {len(ids)} CMF{'s' if len(ids) > 1 else ''} for this crash type show no reduction (CMF ≥ 1; IDs {', '.join(ids)})")
        else:
            out.append(f"{psc}{f' (CMF {ids[0]})' if len(ids) == 1 else ''}: {kind}")
    return out


def facts_id(facts_json: str) -> str:
    """Identity of an audit's facts; reviews of the audit store it so a re-run audit does not show stale reviews."""
    return hashlib.sha256(facts_json.encode()).hexdigest()[:16]


def write(facts: dict, memo_md: str, out: Path, conflict_rows: pd.DataFrame | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts, indent=1, default=float))
    (out / "memo.md").write_text(memo_md)
    if conflict_rows is not None:
        conflict_rows.to_csv(out / "conflicts.csv", index=False)
