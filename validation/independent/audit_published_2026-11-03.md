# Independent audit of published NearMissLens cases (2026-11-03)

Auditor: an independent agent. Before grading I read only `TESTING.md` and the case JSON. I did not read README.md, BENCH.md or BENCH_PREREG.md. I ran no `nml` command and made no paid calls.

To check sources, I downloaded every cited page and compared each quote with the page text. I also queried each city's **public crash record** directly: DataSF `ubvf-ztfx`, SDOT Collisions All Years (ArcGIS), Chicago `85ca-t3if` and NYC `h9gi-nx95`. Each query counted crashes within 100 m of the corner over the case's 5-year window. This let me settle several internal contradictions rather than only flag them. Where I read code, it was only to explain a pattern after I had graded the cases.

## 1. Sample

The population is every published case:
- T21c/d/e: `"finished": true`.
- T25: `"status": "published"`.

| file | cases | published |
|---|---|---|
| experiment_T21c.json | 12 | 11 |
| experiment_T21d.json | 12 | 12 |
| experiment_T21e.json | 12 | 10 |
| experiment_T25.json | 12 | 11 |
| **total** | 48 | **44** |

To draw the sample, I listed every published case as (file, index), sorted the list, then ran `random.Random(20261103).sample(cases, 12)`. The draw, in order:

1. (T21c, 5)
2. (T21c, 10)
3. (T21c, 11)
4. (T25, 8)
5. (T21d, 1)
6. (T21c, 9)
7. (T21c, 3)
8. (T25, 0)
9. (T21d, 5)
10. (T25, 3)
11. (T21e, 11)
12. (T21c, 8)

## 2. Results table

| # | case | corner | grade | one-line reason |
|---|---|---|---|---|
| 1 | T21c[5] | 4th Ave & Pike St, Seattle | CLEAN | Quote verbatim. The corner does have an LPI (SDOT layer: 4th Ave & Pike, east leg, 2020). 211 injury crashes / 2 killed matches SDOT (212 / 2). Both "cannot be checked" verdicts are right. |
| 2 | T21c[10] | Mission St & Precita Ave, SF | MINOR | Facts and numbers right (DataSF 14 / 0). But a curb-grass report, which the city routes to Public Works (`PW:BSM`), ends in a letter to SFMTA. |
| 3 | T21c[11] | Howard St & 4th St, SF | **ERROR** | Finding D7 says the record contradicts "12 injury crashes since 2021-11-02, 0 killed". Its own D4 finding, its letter and DataSF (12 / 0) all confirm that sentence. |
| 4 | T25[8] | Broadway & E Pine St, Seattle | MINOR | Quotes verbatim, corner right, verdicts right. But it values a lighting fix for a corner with "no street lighting" while 137 of 146 dark crashes here are coded "Dark - Street Lights On". |
| 5 | T21d[1] | Aurora Ave N & N 97th St, Seattle | **ERROR** | Letter: "No one was killed". Its own finding and SDOT data: 4 killed. |
| 6 | T21c[9] | 16th St & Julian Ave, SF | **ERROR** | Letter: "No one was killed in this period". Finding and DataSF: 2 killed. |
| 7 | T21c[3] | Moscow St & France Ave, SF | **ERROR** | Rules the source's Oct 2026 death and murder charge "contradicted by the record". The record ends before the crash (Aug 2026), so the right verdict is "cannot be checked". |
| 8 | T25[0] | Broadway & W 262nd St, Bronx | CLEAN | Quotes verbatim, corner right. Pedestrian/cyclist injuries and the 2 killed match NYC Open Data. The "14" depends on how injury crashes are defined (see below). |
| 9 | T21d[5] | Rainier Ave S & S Henderson St, Seattle | MINOR | Quotes verbatim, corridor verdicts right, 23 / 0 matches SDOT. The LPI estimate (−33%, −52% to −13%) is given at 366 sites, while other cases give the same estimate at 371 sites. |
| 10 | T25[3] | Kilbourn Ave & Belmont Ave, Chicago | **ERROR** | Letter says "0 people killed" at the corner where the source's pedestrian was killed (CPD record: 4502 W Belmont, 2026-05-23, fatal). The claim on "1 person killed" is marked "consistent" although the check flagged the death count as not tested. |
| 11 | T21e[11] | Bryant St & Morris St, SF | **ERROR** | Letter: "No people were killed". Finding and DataSF: 1 killed. It also makes a vehicle-only crash record the reason a sidewalk-debris report is urgent. |
| 12 | T21c[8] | 23rd St & Mission St, SF | **ERROR** | Wrong corner. The report (3122 23rd St) is 47 m from 23rd & Shotwell and from 23rd & Folsom, but 337 m (4 blocks) from 23rd & Mission. All record numbers describe the wrong intersection. |

## 3. Per-case evidence

### 1. T21c[5]: 4th Avenue & Pike Street, Seattle (CLEAN)

**Source:** http://sdotblog.seattle.gov/2024/05/16/vision-zero-action-plan/ (SDOT blog, 16 May 2024). The quote "In the past, we have seen nearly a 50% drop in the number of people hit by turning cars at crosswalks with this improvement." is on the page word for word, in the LPI paragraph. "pedestrian head-start walk signals (leading pedestrian intervals)" is also on the page.

**Corner:** the post names no intersection; the task asked for one the program covers.
- The receipt D2 queried the LPI layer around 47.6062,−122.3321, a generic "Seattle" point about 600 m from 4th & Pike.
- I queried the same SDOT LPI layer at 4th & Pike itself: `4TH AVE AND PIKE ST`, LPI_Status Existing, installed 2020, east leg. So "LPI-covered corner" is true.

**Record:** SDOT within 100 m since 2021-11-02 gives 212 injury crashes and 2 killed. The case says 211 / 2, which fits an as-of difference.

**Verdicts:**
- D8 (the "nearly 50%" claim): "cannot be checked" is right. The claim counts people hit by turning cars, which is not the record's program test.
- D9 (17%): "cannot be checked" is right. On the page, the 17% refers to the 25 mph speed-limit change downtown, not LPIs, and the case correctly says "after the change".

**Problems:** none found.

### 2. T21c[10]: Mission Street & Precita Avenue, SF (MINOR)

**Source:** https://mobile311.sfgov.org/open311/v2/requests/202000253083.json. Status open; requested 2026-11-02; 3152 Mission St; description "Over grown grasses at curb". The quote is a `field: value` rendering of the JSON rather than the literal bytes; I treat this as acceptable for the whole sample.

**Corner:** the 311 point is 12 m from Mission & Precita. Correct.

**Record:** DataSF since 2021-11-02 within 100 m gives 14 injury crashes and 0 killed, matching the findings and the letter. The D8 "consistent" verdict is right.

**Photo:** I checked it. Grass growing in the curb joint, walkway clear. The case's "leaves the walkway clear" is accurate.

**Problem (MINOR):** the 311 record's `service_code` is `PW:BSM:Sidewalk and Curb`, a Public Works queue.
- The task asked for "the work order to the agency that owns the road". The case names only SFMTA and drafts an SFMTA safety-study letter.
- Nobody is named for the actual curb maintenance.

### 3. T21c[11]: Howard Street & 4th Street, SF (ERROR)

**Source:** https://mobile311.sfgov.org/open311/v2/requests/202000250507.json. All three field quotes match. The point is 40 m from Howard & 4th, so the corner is correct.

**Photo:** a blue Tesla, rear view, no signs or driveway visible. The finding is accurate, and the plate (visible in the photo) is not repeated in the text.

**Record:** DataSF gives 12 injury crashes and 0 killed, matching D4 and the letter.

**ERROR:** finding D7 reads "The claim stating 12 injury crashes since 2021-11-02 with 0 killed is contradicted by the record check, so it is not relied on for urgency."
- The trace shows the checked sentence was exactly the D4 finding.
- The record holds 12 and 0. A true sentence is published as contradicted, in the same case that states it as fact.
- This is a wrong verdict (TESTING failure 3) and an internal contradiction.

**MINOR, letter:** "the current yellow plus all-red time is below the ITE recommended practice" is stated as a fact. It is the applicability condition of the CMF, not a measurement of this signal. The same sentence appears in cases 11 and 12.

### 4. T25[8]: Broadway & East Pine Street, Seattle (MINOR)

**Source:** https://spdblotter.seattle.gov/2026/04/24/traffic-flagger-hospitalized-after-being-struck-by-dump-truck-in-capitol-hill/. All three quotes are verbatim. The corner is correct. 24 April 2026 is a Friday.

**Verdicts:**
- D6 and D7: "cannot be checked" is right.
- D8 ("41% of crashes in darkness"): "consistent" is right. My SDOT count is 146 of 352, which is 41%.

**Record:** SDOT gives 352 crashes, 109 injury crashes and 0 killed. The case says 350 / 107 / 0, an as-of difference. Parked-car share: I get 19% (HITPARKEDCAR = Y) against the case's 21%, possibly a different field.

**MINOR:** the lighting fix (CMF 7774) is offered as "3.3 crashes a year" and, in the letter, "$1,115,000 in harm avoided per year".
- Its precondition is "the corner has no street lighting now".
- The same police record codes 137 of the 146 dark crashes here "Dark - Street Lights On".
- The site-check caveat is present, but the record the desk already holds answers the check.

### 5. T21d[1]: Aurora Avenue North & North 97th Street, Seattle (ERROR)

**Source:** https://spdblotter.seattle.gov/2026/09/29/hit-and-run-collision-leaves-cyclist-seriously-injured/. The URL redirects to the 10/05 update of the same post, which keeps the "Original Post: 09/29/2026". All three quotes are verbatim. The corner is correct. The D6 and D7 "cannot be checked" verdicts are right.

**Record:** SDOT gives 47 injury crashes and **4 killed**, matching the findings.

**ERROR, letter:** "shows 120 crashes, of which 47 were injury crashes. **No one was killed.**" The letter is published with the case and TESTING says every number in it was checked.

**MINOR:**
- The finding gives "4 people killed, costing about $3.2 million a year at U.S. DOT values". The $3.2M is 47 injury crashes × USDOT's injury-crash value. `harm.py` documents that deaths are not valued, but the finding gives no such caveat, and 4 deaths would add roughly $10M or more a year.
- The finding says flatly "The state transportation department is responsible for Aurora Avenue North". The letter itself hedges with "route designation only; confirm ownership", and its salutation reads "Dear colleagues at route designation only; confirm ownership and SDOT,".
- The lighting fix again: 28 of 33 dark crashes here are "Dark - Street Lights On".

### 6. T21c[9]: 16th Street & Julian Avenue, SF (ERROR)

**Source:** https://mobile311.sfgov.org/open311/v2/requests/202000251762.json. The quotes match. The description names a "red Chevrolet Tahoe"; the case says "red SUV", which is fine. The corner is correct.

**Photo:** red SUV at a worn red curb. Accurate.

**Record:** DataSF gives 38 injury crashes and **2 killed**, matching the findings.

**ERROR, letter:** "38 crashes at this junction, of which 38 were injury crashes. **No one was killed in this period.**"

**MINOR:** "$2.6 million a year" is published next to "2 people killed" without saying deaths are not valued.

### 7. T21c[3]: Moscow Street & France Avenue, SF (ERROR)

**Source:** https://wisevoter.com/world/us/ca/san-francisco/2026/10/26/san-francisco-police-charge-driver-murder. This is an aggregator page with an "AI Illustration". All three quotes are verbatim. NBC Bay Area independently confirms the 1 Oct crash near Moscow & France and the murder charge. The corner is correct, and the suspect's name was printed by the source.

**Record:** DataSF gives 1 injury crash and 0 killed, matching. The dataset's latest crash is 2026-08-31 (data_as_of 2026-10-07), so it cannot contain the 1 Oct 2026 crash.

**ERROR:** D6 says "The claim about murder charges following the October 19 death of the victim is contradicted by the record". D7 says the same of the 29-year-old/death claim.
- A murder charge is not a record field.
- The death happened after the record's last entry.
- By TESTING's definitions this is "cannot be checked" (another period or kind of count).
- A reader is told police data contradicts a death that did happen.

**MINOR:** "0 people killed" is published for a corner where the source reports a death, with no note that the record lags.

### 8. T25[0]: Broadway & West 262nd Street, Bronx (CLEAN)

**Source:** https://westchester.news12.com/2026/01/30/man-dragged-for-minutes-in-north-riverdale-after-being-struck-by-suv/3PDmHdu6cqzCAVpEPsB7Ur. Both quotes are verbatim. The corner is correct and inside NYC.

**Record:** NYC Open Data within 100 m since 2021-10-31 gives 4 pedestrians injured, 1 cyclist injured and 2 killed, all matching.

**Injury-crash count:** the case says 14. I get 16 crashes with ≥1 injured at 100 m, and 14 at 80 m. This is a definitional difference, not an error.

**Note:** one of the 2 deaths in the record is a pedestrian at Broadway & W 262 St on 2026-01-29, apparently this very victim. The case does not say so; nothing in it is wrong.

### 9. T21d[5]: Rainier Avenue South & South Henderson Street, Seattle (MINOR)

**Source:** https://council.seattle.gov/2023/02/23/councilmember-morales-reacts-to-vision-zero-top-to-bottom-review-announces-plans-for-more-comprehensive-action/. All three quotes are verbatim. The 64-collision MLK figure and the Morales attribution are on the page.

**Corner:** Henderson is the named end of the Rainier corridor, so the choice is reasonable.

**Verdicts:** D7 (139 collisions, a corridor-year figure) and D8 (64, another corridor) are both "cannot be checked", which is right.

**Record:** SDOT gives 23 injury crashes and 0 killed, matching.

**MINOR:** "-33% with 95% interval -52% to -13% at 366 sites". Case 1 gives the same interval at 371 sites, and case 5 says "371 sites, confirmed by a second run on 366 sites". So the primary estimate is credited to the replication's site count.

### 10. T25[3]: Kilbourn Avenue & Belmont Avenue, Chicago (ERROR)

**Source:** https://chi.streetsblog.org/2026/05/26/driver-who-fatally-struck-woman-62-near-belmont-kilbourn-cited-for-failure-to-yield. Both quotes are verbatim. "4500 block of West Belmont" is on the page. Kilbourn is 4500 W, so the corner is correct. The victim's name was printed by the source.

**Record:** Chicago portal within 100 m since 2021-10-31 gives 15 injury crashes and **1 fatal**: 4502 W Belmont, 2026-05-23 17:15, the source's own crash.

**ERRORS:**
- **Letter:** "75 crashes, including 14 injury crashes, and **0 people killed**". This is false, and it is about the very death the case is written about.
- **Claim D6:** "consistent with the record" for "14 injury crashes … 1 person killed". The claim carries the flag "model-read check: no field crashes.harm.deaths_in_record in the receipt", so the death count was not tested. TESTING failure 3 says "consistent" for a number that was not tested. The number happens to be true.

**MINOR:**
- "$959,000 a year" omits the death.
- Lighting fix: 17 of 20 dark crashes are coded "DARKNESS, LIGHTED ROAD".

### 11. T21e[11]: Bryant Street & Morris Street, SF (ERROR)

**Source:** https://mobile311.sfgov.org/open311/v2/requests/202000243279.json. The quote matches. The point is 40 m from Bryant & Morris and 112 m from Harrison & Morris, so the corner is correct.

**Photo:** standing water, debris and dumpsters at the curb. Broadly accurate; "children, elderly people and people with disabilities" is embellishment.

**Record:** DataSF gives 34 injury crashes and **1 killed**, matching the findings.

**ERROR, letter:** "34 crashes and 34 injury crashes. **No people were killed.**"

**MINOR:**
- "A search around the report location returned 152 injury crash records" is given with no radius, next to the 34-crash corner count.
- "88% vehicle-only crashes … $2.3 million a year, supporting urgent action on the sidewalk and curb report" is a non-sequitur: vehicle-only crashes say nothing about sidewalk debris.
- The curb/sidewalk issue (`PW:BSM`, Public Works) is sent to SFMTA.

### 12. T21c[8]: 23rd Street & Mission Street, SF (ERROR)

**Source:** https://mobile311.sfgov.org/open311/v2/requests/202000249406.json. The address is 3122 23rd St at 37.7541117, −122.41478343, and the description says 3120 23rd St.

**ERROR, wrong corner:** coordinates from DataSF intersection records:

| intersection | distance from the report | DataSF injury crashes / killed |
|---|---|---|
| 23rd & Shotwell | 47 m | 27 / 0 |
| 23rd & Folsom | 48 m | 21 / 0 |
| 23rd & Mission | **337 m** | 17 / 0 |

- The task asked for "the nearest intersection". The case reports and letters on 23rd & Mission, four blocks west.
- Its 17 / 0 count is right for Mission but describes the wrong corner, so urgency was judged on another intersection's record.

**Privacy:** handled. The plate (visible on the page and in the photo) appears in the case only as "[plate removed]".

**MINOR:**
- The quote "description: Blue Mazda mx5 with CA plate [plate removed] blocking…" is marked `verified` but is not word for word: the page has the real plate. The redaction is right; the `verified` label is not literally true.
- The photo finding "rear over the sidewalk blocking a driveway apron" overstates the photo: the car sits at the curb, a red-curb segment is visible, and no driveway apron is clearly shown.

## 4. Totals and estimate

| grade | count | cases |
|---|---|---|
| CLEAN | 2 | 1, 8 |
| MINOR | 3 | 2, 4, 9 |
| ERROR | **7** | 3, 5, 6, 7, 10, 11, 12 |

**Share of published cases with an ERROR: 7/12 = 58%, Wilson 95% interval 32% to 81%.** The interval is not corrected for the finite population of 44, which would narrow it a little.

Excluding errors that live only in the letter (cases 5, 6, 11), the cases with an ERROR in the summary, findings, sources or claims are 3, 7, 10 and 12: **4/12 = 33%, Wilson 95% 14% to 61%.**

**Population check:** I scanned all 44 published cases, not just the sample, for the death-count contradiction.
- 15 published cases have a death count above 0 in their findings and also carry a letter.
- In **9 of those 15**, the letter says no one was killed. All are in SF, Seattle or Chicago.
- The NYC and DC letters state deaths correctly.

## 5. Patterns for the builders (most important first)

1. **Letters say "no one was killed" at corners where people were killed.**
   - This happens in 9 of the 15 eligible published cases. In the sample: Aurora & 97th (4 dead), 16th & Julian (2), Bryant & Morris (1), and Kilbourn & Belmont (1, the death the case is about).
   - Cause, from code read after grading: `letter.py` line 70 sums only `pedestrian_killed`, `cyclist_killed` and `motorist_killed`. `harm.py` also adds `any_killed`, which is the only death field in the SF, Seattle and Chicago records.
   - TESTING says every number in the letter was checked. This one gets past the check.
   - This is the most damaging error found: an agency would receive a letter understating fatalities.
2. **Verdicts outside the defined vocabulary, and wrong.**
   - Two sampled T21 cases say "contradicted by the record". In case 3 the "contradicted" sentence is true. In case 7 the claims (a murder charge, a death after the record ends) are uncheckable.
   - Out of sample, I count 10 more "contradicted / differs" findings among the 44. Several look like the same kind of mistake (citywide deaths, a victim's age and date, a count of 116 intersections) and deserve review.
   - The record's last-crash date (DataSF: 31 Aug 2026) should enter the claim frame, so recent crashes come out "cannot be checked".
3. **"Consistent" on numbers the check did not test.** Kilbourn's "1 person killed" was flagged as not tested and still published as consistent. Out of sample, T25[7] has the same flag. A flagged claim should not be able to carry "consistent".
4. **Nearest-intersection selection for 311 reports.** In case 12 the desk chose a named arterial (Mission) 337 m away over two intersections under 50 m away. The 311 point should be snapped to the nearest intersection by distance, and any choice more than about 100 m away should be refused.
5. **Site conditions the record already answers, or that no one measured.**
   - Lighting fixes premised on "no street lighting" are valued in dollars at corners where 80–94% of dark crashes are coded "street lights on" (Broadway & E Pine, Aurora & 97th, Kilbourn & Belmont).
   - Letters state "the current yellow plus all-red time is below the ITE recommended practice" as fact, though it is only the CMF's applicability condition.
6. **Harm dollars published next to death counts without the "deaths not valued" caveat**, for example "4 people killed, costing about $3.2 million a year". The figure is low by design, but readers will take it as total harm.
7. **311 routing.** Curb and sidewalk reports, which the feed itself codes `PW:` (Public Works), are answered with SFMTA letters.
8. **Smaller items:**
   - LPI site count mislabelled (366 vs 371).
   - Redacted quotes marked `verified`.
   - A broken salutation when an owner is "route designation only".
   - Out of sample, two published corners are geocoder strings rather than intersections: "Polish Club of San Francisco, 3040, 22nd Street…" (T21e[9]) and "6th Avenue & Fulton Street, 6th Avenue, Inner Richmond…" (T21c[7]).

**What held up:**
- All 22 checked quotes are on their pages: every one word for word except the deliberate plate redaction, with the 311 quotes as field:value renderings of the JSON.
- Every corner except case 12 matches its source.
- No plate or unprinted name appears in any case text.
- Every crash and death count in the *findings* matches the public record within as-of drift (±2). The errors are in verdicts, letters, corner selection and reasoning, not in the queried counts.
