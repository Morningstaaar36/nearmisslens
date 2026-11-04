# A real case: SDOT's new signal at Dexter Ave N & John St, Seattle

Run on November 4, 2026 on the public live site. A script opened Chrome full screen and clicked every step itself;
nothing was typed by hand. This corner is not in any saved set, test set or registered run. Records are as of
31 October 2026.

## The proposal

SDOT's project page ([Dexter Ave N and John St Traffic Signal Project](https://www.seattle.gov/transportation/dexter-john-signal))
says it will replace the interim paint-and-post median and crosswalk with a traffic signal, installed as soon as late
2027. The page justifies it with the corner's recent collisions: 15 in three years, one with a serious injury, and
eleven of the fifteen in 2024.

**The use case.** A resident or a council aide wants to know what the city's own record says about this corner, and
whether the signal is backed by crash-reduction evidence, before the money is committed.

## What the site returned

| Step | Result | Model cost |
|---|---|---|
| Review a project: the new signal | **Not covered by the evidence.** A new signal is not one of the federal Proven Safety Countermeasures, so no reduction can be promised; the decision rests on a site study. 4 objections from Muse Spark Open survived the fact check and were answered. | not recorded by this run |
| Check a claim: SDOT's 15 collisions, 1 serious, 11 in 2024 | **0 agree, 0 differ, 3 the record cannot test.** The record counts 5 years to 31 October 2026; SDOT counts 3 years, and one year alone. | $0.11 Meta |
| Look up the corner | 8 injury crashes in five years, about $548,000 a year in harm; 88% of its crashes are angle crashes, against 16% at the city's worst locations; SDOT is the only road owner | none (no model) |
| Draft the letter | **Refused by the checker on every draft**, a fault this case found (below) | cents |

Screenshots: [the review's verdict](1_review_verdict.png), [the claim check](2_check_tally.png),
[the corner](3_corner_glance.png), [the refused letter](4_letter_refused_before_the_fix.png). The text of every
screen is in [`page_text.json`](page_text.json).

## Checked by hand against the city's own data

Seattle's collision records for the corner, by year: 2023: 2, 2024: 14, 2025: 1, so 17 crashes from 2023 to 2025,
8 of them with an injury. SDOT's page says 11 in 2024. Both show 2024 as the bad year. The counts differ because
SDOT's page does not say which area or which kinds of crashes it counts. The tool was right to answer "cannot test"
rather than "differs".

## What this case found wrong

1. **Every letter was refused.** A sentence naming "high-friction pavement" read to the checker as a claim that the
   pavement's friction is low, a site condition that must be checked first. Naming a fix no longer counts as stating
   its condition; stating the condition still does ("the corner has no street lighting"). Fixed and tested
   (`tests/test_geocode_city.py`).
2. **The memo said "Overall verdict is outside_evidence"**, the code's name for the verdict. The memo gate now refuses
   a verdict's code in the prose and asks for its words (`tests/test_review.py`).
3. **Claims about one year or three years cannot be tested.** The record is read over five whole years, so a
   single-year claim is "cannot test". This is a limit, written in EVIDENCE.md.
