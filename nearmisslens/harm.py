"""What the crashes cost, in the U.S. DOT's official values (Benefit-Cost Analysis Guidance, 2026 Update, Table A-1,
2024 dollars; nearmisslens/data/usdot_bca.json). Police records give injury crashes, not the KABCO severity of each
injury, so every injury crash takes USDOT's injury-crash value and deaths are not valued separately: a fatal crash
counts as an injury crash, so the dollar figures are low rather than high.

A fix's value is its expected injury crashes avoided per year times that value. Its break-even cost is the present
value of that stream over an assumed 10-year life at USDOT's 7% real discount rate: a fix that costs less pays for
itself in avoided harm."""
from __future__ import annotations

import json
from pathlib import Path

BCA = json.loads((Path(__file__).resolve().parent / "data" / "usdot_bca.json").read_text())
INJURY_CRASH_USD = BCA["per_crash"]["injury_crash"]
RATE = BCA["real_discount_rate"]
LIFE_YEARS = 10


def present_value_factor(years: int = LIFE_YEARS, rate: float = RATE) -> float:
    """Present value of $1 a year for `years` years, received at the end of each year."""
    return (1 - (1 + rate) ** -years) / rate


def junction(cr: dict, years: int) -> dict | None:
    """The yearly cost of the junction's injury crashes in the record."""
    if not cr or "error" in cr or not cr.get("injury_crashes"):
        return None
    per_year = cr["injury_crashes"] / years
    killed = sum(cr.get(k, 0) for k in ("pedestrian_killed", "cyclist_killed", "motorist_killed", "any_killed"))
    return {"injury_crashes_per_year": round(per_year, 1), "usd_per_year": round(per_year * INJURY_CRASH_USD, -3),
            "deaths_in_record": int(killed), "value_per_injury_crash_usd": INJURY_CRASH_USD,
            "dollar_year": BCA["dollar_year"], "source": BCA["source"]}


def option(avoided_per_year: float, targets: str, cr: dict) -> dict:
    """Dollar value of one ranked fix: injury crashes it avoids per year x USDOT's injury-crash value. A target group
    counted over all crashes (not only injury crashes) is scaled by the junction's share of injury crashes."""
    share = 1.0 if "injury" in targets else (cr.get("injury_crashes", 0) / max(cr.get("crashes", 0), 1))
    avoided = avoided_per_year * share
    usd = avoided * INJURY_CRASH_USD
    return {"injury_crashes_avoided_per_year": round(avoided, 2), "harm_avoided_usd_per_year": round(usd, -3),
            "break_even_cost_usd": round(usd * present_value_factor(), -3)}
