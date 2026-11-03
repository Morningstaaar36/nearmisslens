# Independent test, round 3: program intake (`nml intake`) and review of what it finds

Tester: independent agent (did not build the tool). Date: 2026-11-04 (Dhaka), 01:12 to 01:28.
Commit tested: `386e18ba5964598c1661c233681283268557e233`. Settings: `NML_BUDGET_USD=99 NML_ASOF=2026-10-31`.
Read beforehand: `TESTING.md`, plus `nearmisslens/intake.py` and `tests/test_intake.py` (to explain a miss, after the runs).
Not read: README, BENCH*, other files under validation/independent/, programs.json.

## 1. Results

| Input | What ran | Outcome | Expected | Grade | Reason |
|---|---|---|---|---|---|
| 3 DDOT NOI pages (NOI-25-104, -161, -148), `--city dc` | `nml intake ... --json` | 3 kept, 0 refused, 0 unreadable, $0.0181, 11 s | 3 single-intersection projects, planned, no cost | **PASS** | All 3 found at the right corner, passages word for word, no cost invented. These pages are trivially easy: one project each, in a one-line description. |
| SFMTA Contract 66 New Traffic Signals (my choice; updated after Dec 2025), `--city sf` | `nml intake ... --json` | 11 kept, 0 refused, $0.0178, 21 s | 14 locations, all planned, no cost | **PARTIAL** | Recall 11/14. All three intersections where three streets meet were left out, and none appears in `refused`, so the drop is silent. The 11 it kept are all correct. |
| "New crosswalk and daylighting at 16th Street SE & Frankford St SE" (from run 1), `--city dc` | `nml review ... --json` | published, "not covered by the evidence", $0.045 + $0.0257, 406 s | Right corner; both parts registered; verdict that follows from receipts | **PARTIAL** | Right corner, and registering both parts as Crosswalk Visibility Enhancements is defensible. But the verdict depends on "this site is not known to be a school crossing", while the DDOT notice says the crosswalks serve Moten Elementary and the receipts list a Safe Routes to School project at this corner. Also, 2 of the 3 injury crashes credited to the corner (the pedestrian and the cyclist) are at the 16th St / Morris Rd end, not at Frankford. |
| "New traffic signals at Cesar Chavez Street & Florida Street" (from run 2), `--city sf` | `nml review ... --json` | published, "not covered by the evidence", $0.0308 + $0.0249, 187 s | Right corner, crash record for this corner | **FAIL** | The memo says this corner "had 23 injury crashes" and that the harm is $1.6M a year. DataSF's own intersection fields put only 3 of the 22 crashes in that circle at Cesar Chavez & Florida; 13 are at Alabama and 6 at Bryant. That is failure type 1 in TESTING.md (a number attributed to the wrong thing). The memo title reads "other at Florida Street…". The verdict text says "no crash-modification study fits this fix", but the real reason is narrower: signals are not on the federal Proven Safety Countermeasures list. |

## 2. Evidence per input

### 2.1 Intake on the DDOT notices of intent (run 1)

**What I found myself.** I read each page through the Confluence REST API (`/wiki/rest/api/content/<id>?expand=body.view`) and also downloaded each attached NOI PDF.

| Page | Project on the page | Status the page gives |
|---|---|---|
| NOI-25-104-PSD | New crosswalk and daylighting at 8th Street NW & Highland Avenue NW | NOI (intent); comment period "CLOSED" (14 May 2025) |
| NOI-25-161-PSD | New crosswalk and daylighting at 16th Street SE & Frankford St SE | NOI; CLOSED (25 Jul 2025) |
| NOI-25-148-PSD | Curb extension with sidewalk at 32nd Place NW & Tennyson Street NW | NOI; CLOSED (16 Jul 2025) |

**Recall:** 3/3. Nothing missed.

**Precision:** all 3 are real, at the right intersection, and marked "planned or proposed". That is the only status the page supports: "CLOSED" refers to the comment period, not to construction. No cost is on any page or PDF, and none was invented (`cost_usd: null`, `cost_covers: "not stated"` for all three).

**Passages:** each `source_says` is the page's own "Description" line. I checked all three programmatically against my own text extraction, and all are on the page word for word.

**Refusals:** none, and none were needed.

**Problems and caveats**
- This was an easy test. Each page holds one project in one sentence, so it says little about recall on real lists.
- Intake reads the HTML only, not the attached PDF. The PDF for NOI-25-161 says the crosswalks are "to provide pedestrian access from the new sidewalks to Moten Elementary School". Intake's `text` does not carry that context, and it changes the review's evidence fit (see 2.3).
- NOI-25-148 is mainly a sidewalk-gap project: the curb extension exists to save two heritage trees, not as a safety countermeasure. Intake kept it as an intersection safety project, which is literally fine, but a program reviewer should know it is not really a safety proposal.
- Intake marks the projects "planned" in good faith. However, the NOIs expected implementation in mid-2025, and the review receipts list "Citywide Federal Safety Improvements (Construction) 2025" and "Safe Routes to School – Sidewalk Construction 2025" at 16th & Frankford. By the as-of date (2026-10-31) some of this work may already be built. Nothing in intake or review flagged this. I did not verify it on the ground.

### 2.2 Intake on SFMTA Contract 66 New Traffic Signals (run 2)

**Page:** https://www.sfmta.com/projects/contract-66-new-traffic-signals. It records an Oct 2025 hearing and a Dec 2025 board approval, and construction is planned for Fall 2027 to Fall 2028. It is not on the excluded list. The page says "new traffic signals at twelve locations, … upgrades … at one location, and … a new pedestrian activated flashing beacon at one location". That is 14 locations, all planned, with no costs.

| # | Location (page text) | Intake |
|---|---|---|
| 1 | 4th Avenue and Fulton Street, new traffic signals | kept |
| 2 | 4th Street and Long Bridge Street, new traffic signals, developer funded | kept |
| 3 | 4th Street and Mission Rock Street, new pedestrian activated flashing beacons, developer funded | kept |
| 4 | 10th Avenue and Lincoln Way, new traffic signals | kept |
| 5 | 28th Street and Guerrero Street, new traffic signals | kept |
| 6 | 39th Avenue and Fulton Street, new traffic signals | kept |
| 7 | **41st Avenue, Chain of Lakes Drive, and Lincoln Way, new traffic signals** | **missing, not in `refused`** |
| 8 | 45th Avenue and Lincoln Way, new traffic signals | kept |
| 9 | Alemany Boulevard and Cotter Street, new traffic signals | kept |
| 10 | **Castro Street, Divisadero Street, and Waller Street, new traffic signals** | **missing, not in `refused`** |
| 11 | Cesar Chavez Street and Florida Street, new traffic signals | kept |
| 12 | Great Highway and Lincoln Way, traffic signal upgrades | kept |
| 13 | La Playa and Lincoln Way, new traffic signals | kept |
| 14 | **Mary Street, Mint Street, and Mission Street, new traffic signals, developer funded** | **missing, not in `refused`** |

**Recall:** 11/14 (79%). The three misses all share one trait: three streets meet at one junction. They are real single intersections, and one, Castro/Divisadero/Waller, is a well-known complex junction. The cause is in the code. `INSTRUCTIONS` defines a project as "ONE intersection (two named streets that cross)", and `check_project` refuses any intersection that is not exactly two streets. The model therefore never submitted these three, so `refused` stays empty and the CLI summary reports "0 refused". A user reading the output has no way to know that 3 of 14 projects were dropped. TESTING.md promises "everything refused is listed with why" (as does the intake.py docstring), and that promise is not kept for this class.

**Precision:** 11/11 are real, at the intersection the page names, with the right treatment. For example, item 3 is correctly recorded as beacons, not signals, and item 12 as "upgrades", not new signals. All are correctly "planned or proposed".

**Passages:** 11/11 are word for word on the page; I checked programmatically. Each list item carries both streets and the work, so `treatment_says` was correctly null.

**Costs:** none invented. "Developer funded" was correctly not turned into a cost.

**Refusals:** none were reported. Three should have been reported, or kept (see above).

### 2.3 Review: "New crosswalk and daylighting at 16th Street SE & Frankford St SE" (DC)

Saved at `runs/reviews/20261103-192224_frankford_street_southeast_16th_street_s/`.

**Was the memo about the right intersection?** Yes: "Frankford Street Southeast & 16th Street Southeast".

**Was the proposal registered correctly?** Two parts, "New crosswalk" and "daylighting", both registered as Crosswalk Visibility Enhancements. That is defensible, because FHWA's Crosswalk Visibility Enhancements include high-visibility crosswalks and parking restrictions on the crosswalk approach. But the memo's "Each part" table and "Why" list show two identical rows, which looks like a bug to a reader. The title also drops "daylighting".

**Does the verdict follow from the appraisal?** Mechanically, yes: both parts are `outside_evidence` because "CMF 2697 was measured only at school crossings, and this site is not known to be one". On the facts, that premise is wrong:
- the DDOT notice for this very project says the crosswalks give access to Moten Elementary School;
- the review's own receipt D3 lists "Safe Routes to School – Sidewalk Construction" (2025) at this corner;
- in the DC crash data, 1565 Morris Rd SE (Moten Elementary's address) lies inside the 100 m circle.

The site most likely is a school crossing, so the evidence the tool says is missing may in fact apply. Part of the blame lies with intake, whose `text` dropped the school context, and part with the review, which ignored a school signal in its own receipts.

**Is the crash record attributed to the right place?** Only partly. I re-queried DC's crash layer (MapServer/24) within 100 m of the corner since 2021-10-31 and got the same 14 crashes the tool did. Of the 3 injury crashes:
- the pedestrian injury is at "2501 15th Place SE";
- the cyclist injury is at "1565 Morris Road SE" (the 16th / Morris Rd end);
- only the driver injury is at "2420 16th Street SE" (Frankford).

The memo writes "Frankford Street Southeast & 16th Street Southeast had 3 injury crashes … 1 pedestrian injured, 1 cyclist injured". That credits a neighbouring intersection's pedestrian and cyclist crashes to this corner. It does not change this verdict, but the red team then argues from those two crashes (O2, O3).

**Red team.** O1 to O4 all make one argument in four forms: "there is harm here, so don't dismiss it for lack of a CMF". They do push against the verdict, but all of them rest on the crash circle described above. O4's "exceeds typical threshold" is an assertion no receipt supports. The answers address each objection, but by repeating the verdict ("no applicable evidence"), and none engages with the substance. No objections were dropped.

**Other problems**
- The internal label `outside_evidence` leaks into the memo text ("Verdict is outside_evidence: …").
- Receipt D4 has `"recorded": {"killed": true}`, a schema flag, next to `deaths_in_record: 0`. The memo correctly says 0 killed, but the receipt is confusing to anyone checking numbers by hand.

### 2.4 Review: "New traffic signals at Cesar Chavez Street & Florida Street" (SF)

Saved at `runs/reviews/20261103-192540_florida_street_cesar_chavez_street_san_f/`.

**Was the memo about the right intersection?** The corner is named correctly, but the crash record it reports is mostly about other intersections. I queried DataSF `ubvf-ztfx` within 100 m of the OSM point for Cesar Chavez & Florida (37.74844, -122.40952) since 2021-10-31 and got 22 crashes; the tool's center gave 23. By DataSF's own `primary_rd | secondary_rd` fields:

| Coded at | Crashes |
|---|---|
| Cesar Chavez St & Alabama St | 13 |
| Cesar Chavez St & Bryant St | 6 (one is "109 ft West") |
| **Cesar Chavez St & Florida St** | **3** |

Two more signs point the same way:
- Three of the crashes have "Red signal – driver or bicyclist responsibilities" as their factor, at a corner the city is proposing to signalise because it has no signal today.
- The owner receipt (D5) lists Alabama St and Bryant St among "the roads" here.

Yet the memo states: "Florida Street & Cesar Chavez Street had 23 injury crashes … that harm costs about $1.6 million a year." Both numbers are about 7x too high for this corner. This is failure type 1 in TESTING.md: a number attributed to the wrong thing. The red team's O1 ("23 injury crashes and 32 injured") and O2 ("6 dark crashes") rest on it, and so do the option estimates (pavement friction "$117,000 a year").

**Was the proposal registered correctly?** Countermeasure "other". That is honest, because a new traffic signal is not on FHWA's Proven Safety Countermeasures list. But the memo title renders as "**Before you commit: other at Florida Street & Cesar Chavez Street**", which is an internal value shown to the reader.

**Does the verdict follow?** "Not covered by the evidence" follows from the code's rule: not a PSC, so no CMF is applied. But the verdict text says "no crash-modification study fits this fix at this site". That overstates the rule. The HSM (Part D, intersections) and the CMF Clearinghouse do carry CMFs for converting stop control to signal control; the tool simply does not consult them for non-PSC fixes. The "Why" line states the true reason, so the headline and the reason disagree.

**"No crash pattern here stands out" (D2).** For most patterns in D2 (left-turn right-of-way 6/23, darkness, night, unsafe speed), `city_share` is 0.0 and `p` is null: the city baseline was never measured. The statement is therefore untested for those patterns, not shown. The answer to O2 relies on this untested claim.

**Red team.** O1 to O3 argue against the verdict. O4 (SFMTA owns the road, so the project is feasible) and O5 (no cost, no benefit-cost support) do not argue against "not covered by the evidence": O5 agrees with it. The answers address each objection only by restating the verdict.

**Other problems**
- The `outside_evidence` label leaks again ("…is outside_evidence. The single part, new traffic signals (other), is outside_evidence…").
- The memo offers Rectangular Rapid Flashing Beacons (0.1 crash/yr) as an alternative on a multi-lane arterial where the city is installing a full signal. It is only a finding, not a recommendation, but it is not useful.

## 3. Overall

**What held up**
- Intake precision. 14 of 14 kept projects were real, at the corner the page names, with the right treatment and the right "planned" status. All 14 passages are verbatim, and no cost was invented. It is cheap and fast (about $0.018 and 11 to 21 s per run).
- The DDOT NOI pages, which an earlier round reportedly struggled with, were read.
- Both reviews ran end to end, published, named the right corner, and kept the verdict set by code. The objection gate dropped nothing incorrectly.

**What did not hold up**
- Intake recall on a real list (11/14), with silent loss of junctions where three streets meet.
- The crash record behind each review is a 100 m circle, credited to the named corner. Near closely spaced intersections it reports other corners' crashes as this one's. In SF that inflated the count about 7x. In DC it moved the pedestrian and cyclist injuries from 16th & Morris to 16th & Frankford.
- Evidence fit ignored context that intake dropped and that the review's own receipts held (a school crossing).
- Presentation: internal labels (`other`, `outside_evidence`) reach the memo, and parts are duplicated in the table.

**Top 3 problems, ranked**
1. **Crash counts are attributed to the corner from a 100 m circle that captures neighbouring intersections.** For Cesar Chavez & Florida, the memo reports 23 injury crashes and $1.6M a year in harm; DataSF codes only 3 of those crashes at that intersection (13 at Alabama, 6 at Bryant). This is a published number about the wrong thing, and the red team, the harm figure and the option estimates all inherit it. The data has intersection fields (`primary_rd`/`secondary_rd`, `cnn_intrsctn_fkey` in SF; `NEARESTINTSTREETNAME` in DC) that would have caught it.
2. **Intake silently drops intersections where three streets meet.** 3 of 14 SFMTA locations (41st/Chain of Lakes/Lincoln, Castro/Divisadero/Waller, Mary/Mint/Mission) are missing and not listed as refused, despite the promise that everything refused is listed with why. A directorate using `portfolio --from-url` would lose about a fifth of the program without being told.
3. **The evidence check misses facts in the source and in its own receipts.** The DC review rules "not a school crossing" for a crosswalk the agency built for Moten Elementary, with an SRTS project in receipt D3. Separately, "no crash-modification study fits this fix" is stated for new traffic signals, when the truth is that the tool does not look outside the PSC list. Both make "not covered by the evidence" look more authoritative than it is.

Lesser problems:
- `other` and `outside_evidence` leak into memo text and titles.
- Duplicate part rows in the memo.
- "No crash pattern stands out" is asserted where the city baseline is 0.0 or null.
- Red-team answers mostly restate the verdict.
- Intake ignores attached PDFs.
- Possible already-built work (2025 DDOT construction at 16th & Frankford) went unflagged.

## 4. Totals

| Run | Meta | Muse Spark Open | Time |
|---|---|---|---|
| Intake, DDOT NOIs | $0.0181 | none | 11 s |
| Intake, SFMTA Contract 66 | $0.0178 | none | 21 s |
| Review, 16th St SE & Frankford St SE | $0.045 | $0.0257 | 406 s |
| Review, Cesar Chavez St & Florida St | $0.0308 | $0.0249 | 188 s |
| **Total** | **$0.1117** | **$0.0506** | **about 10.5 min of runs; about 16 min of wall clock** |

- Total paid: $0.1623 across 4 paid runs, against a limit of 6 runs and about $0.50.
- My own checks (Confluence API, DataSF, DC GIS, Nominatim) were free public queries.
- Commit tested: `386e18ba5964598c1661c233681283268557e233`.
