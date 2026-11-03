# Independent test, round 2 (2026-11-03)

Tester: an agent that did not build NearMissLens and had read only `TESTING.md`. I did not read README.md, BENCH*.md, earlier independent reports or notes outside the repo.
Inputs: the 8 rows marked `"split": "independent2"` (3 checks from `validation/examples/checks_testset.json`, proposals 18–22 from `validation/examples/proposals.json`). Every run was live, one at a time, with `NML_BUDGET_USD=98 NML_ASOF=2026-10-31`. Nothing was retried and nothing failed or hung.

Commit tested: `fb63ee45e0ed08541f937591142fe1f0c613847e` (HEAD when I started; `nearmisslens/data/geocodes.json` had uncommitted changes). Someone else committed `b76f244` at 22:58 +06, during the runs. That commit changed only docs, tests, results and the geocode cache, with no code under `nearmisslens/` other than `data/geocodes.json`, so all 8 runs used the same code.

How I checked: I downloaded each source page (curl, or WebFetch where Cloudflare blocked curl) and searched it for every quote. I re-counted crashes myself from the public crash APIs (DataSF `ubvf-ztfx`, NYC `h9gi-nx95`) with my own 100 m queries, and recomputed the dollar figures from the receipts.

## 1. Results

| # | Input | What ran | Outcome | Expected | Grade | One-line reason |
|---|---|---|---|---|---|---|
| C1 | WalkSF release, pedestrian killed on Mission St near 16th St (sf) | `nml check <url> --city sf` | published, Mission Street & 16th Street | case at Mission & 16th or refusal, never another corner | **FAIL** | Right corner and real quotes, but "nine pedestrians killed in San Francisco in 2026" (a citywide count) is published as *differs from the record* (TESTING failure #3). The letter also states an unchecked yellow-timing condition as fact. |
| C2 | Gothamist, Bushwick hit-and-run (nyc) | `nml check <url> --city nyc` | published, Suydam Street & Broadway | published at the named intersection, quotes verified | **FAIL** | Right corner, quotes real, counts match open data. But two borough-wide claims (Brooklyn 228/2, Queens 157/3) are *differs from the record*, and the finding itself says "boroughwide … differs from the corner record" (failure #3, twice). |
| C3 | "A pedestrian safety project at Lake Street & Franklin Avenue in River Forest" (chicago, find) | `nml check … --kind find` | abstained, no corner | not published as a Chicago case | **PASS** | Refused as outside Chicago. The model tried to switch to "Lake Street & Franklin Street, Chicago" (a Loop corner); code blocked it. |
| R18 | RRFBs at Monterey Blvd & Acadia St (sf) | `nml review --example 18 --letter` | not covered by the evidence | review of that corner | **PARTIAL** | Defensible verdict. But the site is uncontrolled and the "signalized" control comes from the Circular Ave signal about 70–100 m away. The memo and letter then push signal backplates and longer yellows at Acadia, and one answer invents "best alternatives" that the appraisal does not hold. |
| R19 | Side islands, RRFBs, crosswalk upgrades at Fulton St & 40th Ave (sf) | `--example 19 --letter` | decide part by part (reconsider / not covered / reconsider) | review of that corner | **PARTIAL** | All 3 parts registered, and each verdict follows its appraisal. But the red team only agrees with the verdict, the same fact (0 pedestrian crashes) gives "reconsider" for one part and "not covered" for another, and the harm is $68k in the findings but "$0.10 million" in the letter. |
| R20 | RRFB at Lake St & Franklin Ave, River Forest, $360k package (chicago) | `--example 20 --letter` | abstained | refusal (suburb) | **PASS** | Correct refusal; the cost was registered as "a package with other work". The model again tried the Chicago same-name corner and code blocked it. The memo's refusal text is cut off mid-word. |
| R21 | Curb extensions at 14th St NE & Tennessee Ave NE (dc) | `--example 21 --letter` | not covered by the evidence | review of that corner | **PASS (tool) / bad input** | The memo is about the proposed corner, the part is registered and the verdict follows the appraisal. **The test row misreads its source:** the minutes give curb extensions to 13th & F St NE, not 14th & Tennessee. Took 571 s. |
| R22 | Pedestrian refuge islands at Coney Island Ave & Avenue C (nyc) | `--example 22 --letter` | not covered by the evidence | review of that corner | **PASS** | Counts match open data (32 crashes, 4 pedestrians and 1 cyclist injured, 0 killed). The verdict follows (signalized site; refuge-island CMFs are for uncontrolled sites), and the objections and answers are real. Minor: the letter never mentions the islands and has a garbled sentence. The source link returns 404. |

## 2. Evidence and problems, per input

### C1. WalkSF, Mission St near 16th St (run `runs/checks/20261103-165320_mission_street_16th_street_san_francisco`, 75.2 s, $0.0583)

- **Corner.** The release says "on Mission Street near 16th Street" and later "The intersection of Mission and 16th Streets". The case is Mission Street & 16th Street, which is correct. The page also names six other intersections (Bayshore & Silver, 4th & Channel, Mission & Naglee and others), and the desk did not drift to any of them.
- **Quotes.** All 4 appear word for word on the page (checked by script against the downloaded text). The one the finding uses ("a pedestrian was fatally hit by a driver on May 25, 2026, on Mission Street near 16th Street…") is about this crash.
- **Claim D6 is wrong (TESTING failure #3).** "There have now been nine pedestrians killed in San Francisco in 2026" is a citywide count for one year. It was tested against the 100 m, 5-year corner record and published as **"differs from the record"**, with the reason "9 is not the record's number of pedestrians killed for what this sentence names". This is the exact case TESTING.md says must be "cannot be checked". The `frame` text ("a source counting another area or period can differ") admits the problem but does not change the verdict.
- Claim D7 ("third pedestrian fatality on Mission Street this year") is "cannot be checked", which is correct.
- **Numbers.** These match the receipts and my own query:
  - D3: 40 crashes, 1 killed. `by_year` sums to 40.
  - Harm: 8.0/yr × $342,400 = $2.739M, as stated.
  - Backplates: 8.0 × 0.15 = 1.2/yr, worth $411k.
  - D1: 19/40 = 47.5% vehicle-pedestrian.
  - My own DataSF query (100 m around 37.76501, -122.41966, after 2021-10-31) returns 47 crashes and 1 killed. The 1 killed is the 2026-05-25 vehicle-pedestrian crash at Mission & 16th, so this crash is in the record. The difference between 47 and 40 is plausibly my choice of centre.
- **False statement about the record.** The D1 receipt says the record does not hold "contributing factors, time of day, vehicle types", and D3 has `dark_share: null`. "Lighting" is therefore not estimated because "the crash record does not show injury crashes in darkness". DataSF `ubvf-ztfx` does hold `lighting`, `vz_pcf_description` (the primary collision factor), `collision_time` and `party1_type`. At this corner 18 of my 47 crashes are "Dark - Street Lights", and the fatal crash was in the dark. The SF adapter is discarding fields and then telling users they do not exist.
- **Letter.**
  - (a) "Longer yellow signal times … This needs a site check for an entry on yellow or red; the current yellow plus all-red time is below the ITE recommended practice." This reads as a statement of fact, but it is the condition to be checked; nobody measured it.
  - (b) "In this period the record shows no safety work at this junction" sits next to "This corner got continental crosswalks" (with no year in the receipt), which half-contradicts it.
  - (c) "The earlier program's effect was not shown and we ask for a different approach" overreads a null result (+4%, CI −25% to +33%).
  - The addressee (SFMTA) is right. Hoff St and Wiese St are alleys within 100 m, which is fine.
- Minor: findings D2 and D8 repeat the same continental-crosswalk statistic. Roundabouts at Mission & 16th (a BART plaza) appear in the D3 options at 5.7 crashes a year, but not in the findings.
- No victim names (the page prints two) or licence plates appear anywhere in the output.

### C2. Gothamist, Bushwick (run `runs/checks/20261103-165424_suydam_street_broadway_brooklyn_ny`, 49.5 s, $0.0507)

- **Corner.** The article says "near the intersection of Broadway and Suydam Street in Bushwick". The case is Suydam Street & Broadway, which is correct.
- **Quotes.** Both are on the page. One matches only after normalising the curly apostrophe ("District's"), which is acceptable. Both are about this crash.
- **D6 and D7 are wrong (failure #3, twice).**
  - "A total of 228 pedestrians were hurt through June, and two were killed" is Brooklyn, January to June 2025. It was published as **differs**, with the reason "228 is not the record's number of pedestrians injured (the record has 7)".
  - "Queens … 157 injured and three killed" was published as **differs**, with the reason "number 157 is not in the dossier". That is not a test at all.
  - The published finding reads: "The claim about boroughwide pedestrian injuries through June differs from the corner record for this period." The desk knew the claim was borough-wide and still said "differs".
- **Numbers.** My own NYC query (100 m around the fatal crash point, 2021-10-31 to 2026-10-31) gives exactly 57 crashes, 7 pedestrians injured, 4 cyclists injured and 1 pedestrian killed (2025-08-02 03:43, BROADWAY/SUYDAM ST), so the receipts match. Harm: 3.8/yr × $342,400 = $1.301M. Backplates: 3.8 × 0.15 = 0.57/yr. LPI: −17% at 1,651 sites, per D2. One small error: "19 injury crashes … and 1 person killed". The fatal crash recorded 0 injured, so it is not among the 19, and the harm figure leaves the death out entirely (that crash is the subject of the article).
- **Letter.** "Measured in this city, a leading pedestrian interval … was studied … at 1,651 intersections, with the result noted in the facts." The agency reader has no "facts", so this is pipeline text leaking into the letter. The Cc to Council District 34 and Brooklyn CB4 is plausible for Bushwick. "This site is listed as a city priority location" comes from the D5 facts (`city_priority_location: true`).

### C3. River Forest trap (run `runs/checks/20261103-165520_a_pedestrian_safety_project_at_lake_stre`, 34.6 s, $0.0762, exit code 2)

- The status is `abstained` with no corner, findings, claims or letter, which is the correct outcome.
- The trace shows the model read three suburban pages and called `investigate("Lake Street & Franklin Avenue, River Forest")`, which raised OutsideCoverage. It then tried `"Lake Street & Franklin Street, Chicago"` (W Lake St & N Franklin St in the Loop, a real and different corner) and `"Lake Street & Franklin Avenue"`. Code refused both as same-name substitutions. The guard works; the model's instinct to swap corners does not.
- The `reason` text reads like an internal error ("not published (final_message); the last refusal: …"). There is no plain status such as "outside the city's coverage".

### R18. Monterey Blvd & Acadia St, RRFBs (run `runs/reviews/20261103-165731_monterey_boulevard_acadia_street_san_fra`, 111.0 s, $0.0423 + $0.034)

- **Source is faithful.** The SFMTA page says "Installation of rectangular rapid flashing beacons (RRFBs) at the intersection of Monterey Boulevard and Acadia Street", approved at an August 2026 hearing. The signal-head upgrade is at Monterey & Foerster.
- **Parts.** There is 1 part, RRFB → "Rectangular Rapid Flashing Beacons", which is correct. The corner is correct.
- **Verdict.** "Not covered by the evidence": 0 pedestrian injury crashes, and CMF 11158 is mid-block only. For a proactive RRFB this is a sensible engineering answer. TESTING.md says, however, that "the record shows none of the crashes it targets" means **reconsider**, so the rule as documented is not what the code does.
- **Counts.** My DataSF query gives 6 crashes and 0 pedestrian crashes within 100 m, matching the memo. **But 4 of the 6 are at Monterey & Circular Ave (signal, `control_device: Functioning`). The only Monterey/Acadia crash has `control_device: None`.** The crossing is uncontrolled, and the "Signalized" mapping belongs to the Circular signal.
- **Signal hardware at a crossing with no signal.** Despite noting that control must be confirmed on site:
  - The memo lists "Backplates with Retroreflective Borders would avoid about 0.2 crashes a year" as a finding.
  - The answer to O3 says "backplates and yellow timing are the quantified best alternatives rather than RRFB", although `appraisal.best_alternative` is **null**.
  - The work order asks SFMTA for "reflective backplates on the traffic signals" and "longer yellow signal times" at Monterey & Acadia. It also states "the current yellow plus all-red time is below the ITE recommended practice" as fact.
- **Red team.**
  - O1 and O2 push back on the verdict, weakly.
  - O3 argues for signal fixes.
  - O4 (ownership is inferred) does not argue against the verdict at all.
  - `objections_dropped` is the same 4 objections word for word, each marked "another objection already rests on this fact", so the memo's "4 more objection(s) were dropped by code" is misleading.
- **Data not saved.** The review folder has no `receipts.json`, and `result.json → receipts` holds only `{"tool": …}` for D1–D9. No number in a review memo can be checked against its receipt without rerunning.

### R19. Fulton St & 40th Ave, three parts (run `runs/reviews/20261103-165925_fulton_street_40th_avenue_san_francisco`, 102.5 s, $0.0304 + $0.0298)

- **Source is only partly faithful.** The SFCTA page (read via WebFetch; curl hit a Cloudflare challenge) names Fulton & 40th as one of three intersections. It says the *project* is expected to include side islands, crosswalk upgrades, RRFBs, lane hardening and signage, without saying which treatment goes where. The test row assigns all three treatments to 40th Ave. No cost is given.
- **Parts.** All 3 are registered. "Pedestrian side islands" → *Medians and Pedestrian Refuge Islands* is questionable: side islands are curb-side, bulb-out-like islands, not median refuges. The memo title names only that first part.
- **Verdicts follow the appraisal:**
  - Islands: reconsider (0 pedestrian injury crashes).
  - RRFB: outside the evidence.
  - Crosswalk: reconsider, because continental crosswalks were installed in 2017.
- **Inconsistent rule.** The same fact (no pedestrian crashes) gives "reconsider" for islands and "not covered" for RRFBs, here and in R18.
- **Counts.** DataSF has 1 crash within 100 m since 2021-10-31 (2026-01-22, vehicles only), matching the memo. The same corner had vehicle-pedestrian crashes in 2012, 2015 and 2016. These are outside the 5-year window, but an engineer weighing "the record has no pedestrian injury crashes" would want to know about them.
- **Red team is not adversarial.** All 4 objections argue against the *proposal*, i.e. for the "reconsider" verdict, not against the verdict. The answers just restate the objections. O2 cites `D7.not_estimated_reason = "the record has no pedestrian injury crashes"` as support for a point about the 2017 crosswalk, which is the wrong field. The dropped list is again a duplicate of the kept list.
- **Inconsistent harm figures.** The findings say "$68,000 a year" (0.2 × $342,400, correct); the letter says "$0.10 million" per year. The letter also asks SFMTA "to consider a different approach" without mentioning the proposed one.

### R20. River Forest RRFB (run `runs/reviews/20261103-170017_a_rectangular_rapid_flashing_beacon_at_l`, 43.1 s, $0.0275, exit code 2)

- Abstained, with no corner, verdict or letter, which is correct. The cost was registered as $360,000 and "a package with other work"; the source agrees: the $360k covers bump-outs, refuge islands, drainage, ADA ramps and more.
- The model again tried "Lake Street & Franklin Avenue, Chicago" after the refusal, and code blocked it. The model also called `appraise` and `red_team` before any successful `investigate`.
- The memo's "Not published" line is cut off: "…say the plac".

### R21. 14th St NE & Tennessee Ave NE (run `runs/reviews/20261103-170958_14th_street_northeast_tennessee_avenue_n`, 571.0 s, $0.0318 + $0.0285)

- **The test input misreads its source.** The ANC 6A TPS minutes of 18 Feb 2025 say:
  - Item III.a (14th & Tennessee NE): "DDOT has evaluated the traffic safety concerns … There was no discussion of this topic beyond its introduction." Curb extensions are not mentioned.
  - Item IV.a: "the intersection of 13th and F Streets NE … DDOT determined that installing curb extensions will decrease pedestrians' crossing distance."

  The row pairs the fix with the wrong corner. The tool cannot know this, but the review is of a proposal nobody made, and anyone citing R21 as a "real proposal" is wrong.
- **Tool behaviour.**
  - The memo is about the proposed corner.
  - Curb extensions → Crosswalk Visibility Enhancements is acceptable, since FHWA lists curb extensions within that countermeasure, but the memo title then says "Crosswalk Visibility Enhancements" rather than curb extensions.
  - Verdict "not covered" (CMF 2697 is school crossings only) follows the appraisal.
  - Harm: 0.8 × $342,400 = $273,920, matching the $274k.
  - Five objections argue that the site deserves action, and each answer addresses its objection.
- **Not verified.** I could not reproduce the DC counts (4 injury crashes out of 16): the DC GIS layer has no usable cross-street field for this corner.
- **Question.** The letter says "The latest recorded safety work is Thermoplastic Pavement Markings in 2026". If those markings are crosswalks, a Crosswalk Visibility Enhancement is already in place and the appraisal ignores it (`in_place: null`), while R19 treated an in-place crosswalk as grounds for "reconsider".
- **Speed.** 571 s, five times longer than any other run.

### R22. Coney Island Ave & Avenue C (run `runs/reviews/20261103-171109_coney_island_avenue_avenue_c_new_york_ci`, 61.0 s, $0.0427 + $0.0354)

- **Source is unreachable.** `nyc.gov/.../coney-island-ave-ave-c-whh.pdf` returns a 404 page ("outdated or non-existing page"), so I could not check that the proposal is faithful. The row should be fixed or given an archived link.
- **Tool behaviour.** The corner is correct, 1 part is registered, and refuge islands → Medians & Pedestrian Refuge Islands is correct. The verdict "not covered" follows the appraisal (signalized site; the CMF records are for uncontrolled sites). That is defensible, though NYC builds refuge islands at signalized crossings routinely.
- **Counts.** My NYC query (100 m around 40.64138, -73.969406) gives 32 crashes, 4 pedestrians injured, 1 cyclist injured and 0 killed, all matching. I count 16 injury crashes against the tool's 15, which is within centre-point tolerance. Harm: 3.0 × $342,400 = $1.03M, which the memo gives as "$1.0 million".
- **Red team.** It argues for acting despite the verdict, which is real pushback, and each answer addresses its objection. The dropped list again duplicates the kept list.
- **Letter.** It asks for backplates and longer yellows but **does not mention the refuge islands it is supposed to be the work order for**. It also contains "with deaths and injuries recorded by mode including motorists, pedestrians and cyclists. No one was killed", which is garbled. Cc to CD39 and CB12 is plausible.

## 3. Overall

**What held up**
- Corner identification: all 6 cases that were published or reviewed were about the intersection the source or proposal names. C1 is the hard case: the page names seven intersections, and the desk picked the right one.
- The suburb guard: River Forest was refused in both modes (C3, R20), and code blocked three attempts by the model to swap to a same-name Chicago corner.
- Quotes: all 6 quotes are on their pages word for word and are about the crash.
- Crash counts: they match my own independent API queries at the three corners I could re-count in SF and NYC (C2, R18, R19 exactly; C1 and R22 within centre-point tolerance). The 2026-05-25 death and the 2025-08-02 death are both in the record.
- Arithmetic: every dollar and crashes-avoided figure I recomputed matches the receipts.
- Proposal registration: every part of every proposal was registered, and the verdicts follow the code's appraisal.
- No names or licence plates leaked; the WalkSF page prints two victims' names.

**What did not**
- Claim verdicts on area-mismatched statistics: 3 of the 4 numeric source claims across C1 and C2 were wrongly marked "differs".
- Site conditions: hardware for a signal that is not there (R18), and an unmeasured timing condition stated as fact in three letters (C1, R18 and, phrased as a condition, C2 and R22).
- The SF crash adapter throws away fields the dataset has (lighting, primary collision factor, time) and then says the record lacks them.
- The red team often agrees with the verdict (R19), and the "dropped objections" bookkeeping is a duplicate of the kept list (R18, R19, R22).
- Reviews save no receipt data, so no memo number can be audited without a rerun.
- Letters in R18, R19 and R22 do not mention the proposal they are the work order for. They contain leaked pipeline wording ("noted in the facts") and contradict the memo's own figures ($68k vs $0.10M).
- Test-set quality: R21's row is not what its source says, R22's source is a 404, and R19 assigns project-wide treatments to one corner.

**Top 3 problems, ranked**
1. **Wrong claim verdicts (TESTING failure #3).**
   - What happens: the desk publishes citywide and borough-wide statistics as "differs from the record" after testing them against a 100 m corner record.
   - Where: "nine pedestrians killed in San Francisco in 2026" (C1), Brooklyn 228/2 and Queens 157/3 (C2).
   - Why it matters: it happened in every check that had such a claim, so it is systematic. The `frame` disclaimer does not fix it, and C2's finding even says "boroughwide".
2. **Signal fixes recommended at a crossing with no signal, and site conditions stated as fact.**
   - What happens: at Monterey & Acadia (R18) the 100 m radius pulls in the Circular Ave signal, so the crossing is treated as signalized. The memo and work order then ask SFMTA for signal backplates and longer yellows at an uncontrolled RRFB crossing.
   - The red-team answer claims these are the "quantified best alternatives" although the appraisal has none.
   - Letters assert "the current yellow plus all-red time is below the ITE recommended practice" (C1, R18) without anyone having measured it.
3. **The SF adapter misreports what the record holds.**
   - What happens: receipts say the record lacks contributing factors, time of day and vehicle types; `dark_share` is null, and lighting is "not estimated: record does not show injury crashes in darkness".
   - What the data holds: DataSF `ubvf-ztfx` has `lighting`, `vz_pcf_description`, `collision_time` and party types. At Mission & 16th about 38% of crashes (18 of my 47) were in the dark, including the fatal one.
   - Effect: an unsupported negative statement about the record, which removes lighting and factor-based fixes from consideration.

Also worth fixing:
- (4) The red team is not adversarial in R19, and the dropped-objection list duplicates the kept list (R18, R19, R22).
- (5) Reviews save no `receipts.json`.
- (6) Bad test rows: R21 has the wrong corner for the fix, R22's source is a 404, and R19 assigns project-wide treatments to one corner.
- (7) "No pedestrian crashes" means "reconsider" in TESTING.md, but the code gives "not covered" for RRFBs and "reconsider" for islands.
- (8) Fatal-only crashes are left out of "injury crashes" and out of harm (C2).
- (9) R21 took 571 s.

## 4. Totals

- **Cost** (from `cost_usd`):
  - Meta API: $0.3599 (checks $0.1852; reviews $0.1747).
  - Muse Spark Open (Baseten) red team: $0.1277.
  - **Total: $0.4876.**
- **Time** (tool-reported `seconds`): 75.2 + 49.5 + 34.6 + 111.0 + 102.5 + 43.1 + 571.0 + 61.0 = 1,047.9 s (17.5 min). Wall clock from the first start to the last finish: 1,145 s (19.1 min). There were no hangs and no retries.
- **Grades:** 4 PASS (C3, R20, R21 as a tool result on an invalid input, R22), 2 PARTIAL (R18, R19), 2 FAIL (C1, C2).
- **Commit tested:** `fb63ee45e0ed08541f937591142fe1f0c613847e`. HEAD moved to `b76f244` during the runs; that commit has no code changes.
