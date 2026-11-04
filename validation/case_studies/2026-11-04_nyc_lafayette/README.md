# A new real case: NYC DOT's leading pedestrian intervals on Lafayette Street

Run on November 4, 2026 on the public live site. A script opened Chrome full screen and clicked every step itself;
nothing was typed by hand. These corners are not in any saved set, test set or registered run. Records are as of
31 October 2026.

## The proposal

On April 28, 2026, NYC DOT presented "Bicyclists and Pedestrian Improvements, Lafayette St/4 Av, Prince St to E 15 St"
to Manhattan Community Board 2's Transportation Committee
([presentation](https://www.nyc.gov/html/dot/downloads/pdf/lafayette-st-4th-ave-prince-st-e15-st-apr2026.pdf)).
Page 11 reads:

> Install left turn lane treatment: Plus, Leading Pedestrian Interval (LPI): Prince St, Houston St, Great Jones

**The use case.** A board member or a DOT engineer wants to know whether each of the three intervals is supported by
its corner's own crash record before the board votes and the work is scheduled.

## What the site returned

| Step | Result | Time | Model cost |
|---|---|---|---|
| Review a project: the interval at Lafayette St & E Houston St | **Proceed after a site check**: the estimate holds only if a turning movement is confirmed on site. 4 objections from Muse Spark Open survived the fact check and were answered. | 48 s | $0.052 Meta + $0.044 Muse Spark Open |
| Review a list: all three intervals | Houston St: build after a site check. **Great Jones St: compare first**: backplates are expected to avoid 0.39 injury crashes a year against 0.08 for the interval. **Prince St: reconsider: the city's records show an interval already installed there (2024).** | 70 s | $0.26 |
| Look up the corner (Lafayette St & E Houston St) | 13 injury crashes in five years (3 pedestrians and 5 cyclists injured, 1 person killed), about $890,000 a year in harm, NYC DOT owns both streets | 10 s | none (no model) |
| Draft the letter | A letter to NYC DOT, copying Council District 2 and Community Board 2. Every number was checked; one draft was refused by the checker and fixed. | 5 s | Muse Spark Open, cents |

Screenshots: [the review's verdict](1_review_verdict.png), [the case against it](2_review_case_against.png),
[the ranked list](3_list_ranked.png), [the corner](4_corner_case.png), [the letter](5_corner_letter.png). The full
text of every screen is in [`page_text.json`](page_text.json).

## Checked by hand against the city's own data

- **The interval already at Prince St.** NYC's dataset of leading pedestrian interval signals (Socrata `xc4v-ntf4`)
  lists "Lafayette Street & Prince Street", installed **2024-10-11**, and none at Houston St or Great Jones St.
  [`check_lpi_signals_lafayette.json`](check_lpi_signals_lafayette.json) is the query result. This is what the review
  of the list says. The presentation may mean the interval that comes with the new turn treatment, but the board
  should ask before it is counted as new.
- **The crashes at Houston St.** NYC's crash dataset (`h9gi-nx95`), queried by street names for the same five years,
  has 18 crashes named at Lafayette St & E Houston St:
  - 12 have someone injured, and 1 more has a death (2023-03-25, 07:54, "Traffic Control Disregarded"). That gives
    13 injury crashes, the same as the tool;
  - by name, 2 pedestrians and 4 cyclists are injured; the tool says 3 and 5, because it also counts crashes the city
    placed at the corner by coordinates without street names (the limit measured in T31b).

  [`check_crashes_lafayette_houston_by_name.json`](check_crashes_lafayette_houston_by_name.json) is the query result.

## What this case found wrong, all fixed the same day

The first live runs of this case showed six faults, now fixed and tested:
1. **The death was missing.** The 2023 death is recorded in `number_of_persons_killed` with every by-mode field at
   zero. New York's mapping read only the by-mode fields, so the case and the letter said no one was killed. The
   total is now mapped, and the deaths are the larger of the two counts.
2. **The checker could not see the death total in a letter** (`people_killed`). It refused "1 person was killed" and
   let "no one was killed" pass.
3. **A letter quoting the city's own measured effect of the interval** (−17%, interval −22% to −11%) was refused,
   because the checker saw those figures only inside a sentence.
4. **A letter for a newly searched corner counted the whole 100 m circle**: 23 injury crashes against the case's 12.
   It now uses the corner's own crashes from the first read.
5. **A searched corner offered questions** the server can answer only for listed corners. The form is now replaced
   by a note.
6. **A reason said "injury crashes crashes".**

Fault 1 also affects the saved New York corner reports on the site, which were built before the fix. New lookups are
correct; the saved reports will be right when they are rebuilt.

## Limits of this case

- The presentation gives no cost, so the list could not be fitted to a budget.
- Each verdict depends on a site check: the estimates assume turning movements that public data cannot show.
- The harm figure values injury crashes only; deaths are not valued in it.
