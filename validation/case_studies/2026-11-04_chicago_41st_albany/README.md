# A real case: Chicago's all-way stop at W 41st St & S Albany Ave

Run on November 4, 2026 on the public live site. A script opened Chrome full screen and clicked every step itself;
nothing was typed by hand. This corner is not in any saved set, test set or registered run. Records are as of
31 October 2026.

## The proposal

On September 23, 2026 the Chicago City Council passed ordinance
[O2026-0026671](https://chicago.councilmatic.org/legislation/o2026-0026671/), 50 votes to 0, ordering an all-way stop
at West 41st Street and South Albany Avenue. Stop-sign ordinances like this one are routine aldermanic requests.

**The use case.** Someone at CDOT, or a resident, wants to know whether the corner's crash record calls for it, and
what the evidence supports there, before the signs go up.

## What the site returned

| Step | Result | Model cost |
|---|---|---|
| Review a project: the all-way stop | **Not covered by the evidence.** An all-way stop is not one of the federal Proven Safety Countermeasures, so no reduction can be promised. 4 objections from Muse Spark Open survived the fact check and were answered. | not recorded by this run |
| Look up the corner | **1 injury crash in five years**, no deaths, about $68,000 a year in harm; CDOT is presumed to own both streets (neither has a route number). Rapid flashing beacons, the best supported fix, would avoid about 0.1 crashes a year. | none (no model) |
| Draft the letter | **Refused by the checker on every draft**, a fault this case found (below) | cents |

Screenshots: [the review's verdict](1_review_verdict.png), [the corner](2_corner_glance.png),
[the refused letter](3_letter_refused_before_the_fix.png). The text of every screen is in
[`page_text.json`](page_text.json).

## Checked by hand against the city's own data

Chicago's crash dataset (`85ca-t3if`) records crashes by street address. Since 31 October 2021 it holds 9 crashes at
the corner's own block numbers (4100 to 4101 S Albany Ave, 3100 to 3110 W 41st St); **1 of them has an injury**
(2026-05-10, 4101 S Albany Ave), as the tool says. [`check_crashes_by_address.json`](check_crashes_by_address.json)
is the query result.

The tool places 22 crash records at the corner, not 9: it reads the records' coordinates, and Chicago geocodes
crashes on nearby addresses to the corner. Both counts find the same single injury crash. This is the open-data
question T31b and T32 measure.

**What the record says about the ordinance.** One injury crash in five years is a quiet corner by Chicago's
standards. An all-way stop may still be right for reasons the record does not hold (sight lines, a school, traffic
volumes), but the crash record does not call for it, and no federal study promises it will reduce crashes here.

## What this case found wrong

1. **Every letter was refused.** A sentence naming "better street lighting" read to the checker as a claim that the
   corner has none. Naming a fix no longer counts as stating its site condition. Fixed and tested.
2. **The corner said "1 injury crashes"** and **"Lighting would avoid about 0.0 crashes a year"**. It now says
   "1 injury crash" and "almost none of them (0.0 crashes a year)".
3. **The memo used the verdict's code** ("outside_evidence") in its prose. The memo gate now refuses it.
