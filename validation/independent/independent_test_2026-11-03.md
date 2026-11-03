# Independent test of NearMissLens, 2026-11-03

- Tester: an independent agent. Before testing it had read only `TESTING.md`; README, BENCH and the builders' notes were not opened.
- Commit reported by `git rev-parse HEAD`: `ac70919634c6fa5ec458d8520a78b59e19f318d8`. Another session was writing to `runs/engineer/` while these runs were made, so the working tree may differ from that commit.
- Environment: `NML_BUDGET_USD=87 NML_ASOF=2026-10-31`, live mode. There were 7 runs, made one at a time, with no retries. No code or data was changed.
- Inputs: the rows with `"split": "independent"` in `validation/examples/checks_testset.json` (4 rows) and in `validation/examples/proposals.json` (rows 8, 9 and 10).
- How I checked: I downloaded every source page myself (curl, plus WebFetch for the Sun-Times page, which blocks curl), reduced it to text and compared each quote character by character. The `result.json` files hold no data behind receipts D1–D5 (only `{"tool": ...}`). So I re-counted the crashes myself from the public datasets: Socrata for Chicago, NYC and SF, and the DCGIS MapServer for DC. I used a 100 m buffer around the intersection centroid over 2021-10-31 to 2026-10-31. My counts check the order of magnitude only; they do not reproduce the tool's exact method.

## 1. Summary table

| input id | what ran | outcome | expected | grade | one-line reason |
|---|---|---|---|---|---|
| ind_url_sf | `nml check <walksf.org URL> --city sf` | published, Mission St & South Van Ness Ave; 3 quotes verified | published at Mission & SVN, quotes verified | **PARTIAL** | Right corner and real quotes. But it made up a "claim" from its own number and graded it "consistent". The letter says "0 people were killed" without reconciling the death the source reports, and it states an unsupported signal-timing "fact". |
| ind_url_dc | `nml check <wjla.com URL> --city dc` | published, North Capitol St & New York Ave NE; 4 quotes verified | published at N Capitol & NY Ave, quotes verified | **PARTIAL** | Right corner and real quotes, but none of the quotes gives the location. The summary says "request letter drafted" while `letter` is `null`. It also invents a "state transportation department" for DC. |
| ind_false_statement | `nml check "<…zero injury crashes…>" --as-source --city nyc` | published; claim "differs from the record" (75 injury crashes) | "differs from the record", citing the input | **PASS** | Correct verdict and citation. The letter has small defects (an LPI "in place in 1996", a garbled sentence). |
| ind_true_statement | `nml check "<…66 injury crashes…>" --as-source --city chicago` | published; claim "consistent with the record" | "consistent with the record", citing the input | **PASS** | Correct verdict. Caveat: the expected 66 equals the tool's own count, so this tests self-consistency, not accuracy. My count is 64. |
| proposals #8 chicago_1e736f | `nml review --example 8 --letter` | reconsider (no PHB CMF fits) | (a sensible, correctly reasoned verdict) | **FAIL** | It treats an unsignalised five-way intersection as "Signalized" and recommends signal-only fixes (LPI, backplates) where there is no signal. It charges the whole $1.3M package (realignment, APS, crosswalks) to the beacon and compares that with an alternative's break-even. |
| proposals #9 dc_aa16ac | `nml review --example 9 --letter` | reconsider (LPI already installed 2019) | (a sensible, correctly reasoned verdict) | **FAIL** | It drops the protected left-turn phase, which is the core of the request. The LPI fact is right (I confirmed it in the DDOT layer). One red-team answer ignores the pedestrian death. The letter cites a "2032" project and asserts an untested yellow-time fact. |
| proposals #10 nyc_22c137 | `nml review --example 10 --letter` | reconsider (no refuge-island CMF for signalised sites) | (a sensible, correctly reasoned verdict) | **PARTIAL** | Right corner, right countermeasure, counts match mine. But "reconsider" for hardening painted islands rests only on a missing CMF. Two of five answers dodge or misread. The letter drops the proposal altogether. |

Totals: **2 PASS, 3 PARTIAL, 2 FAIL.** Cost $0.248 Meta + $0.071 Muse Spark Open (Baseten) = **$0.319**. Tool time 1,083 s (18.1 min) across the 7 runs.

## 2. Per input: evidence and problems

### 2.1 ind_url_sf — `runs/checks/20261103-130945_mission_street_south_van_ness_avenue_san/`

**Source** (https://walksf.org/news/for-reporters/press-releases/pedestrian-fatality-mission-south-van-ness-2026/), as I read it:
> "Walk SF learned from the San Francisco Police Department that a pedestrian was fatally hit by a hit-and-run driver yesterday, April 13, 2026, at the intersection of Mission Street and South Van Ness in the South of Market neighborhood in District 6."

- **Corner:** "Mission Street & South Van Ness Avenue, San Francisco". Correct.
- **Quotes:** all three are on the page word for word; only the curly quote marks and apostrophes differ ("City’s", “high-injury network”).
  1. The "Walk SF learned …" sentence supports the reported crash. OK.
  2. "According to the City's traffic fatality tracker, eight of the nine people killed …" is on the page and is used for claim D8. OK.
  3. "Mission Street and South Van Ness Avenue is a wide, sprawling intersection and is on the city's new 2024 "high-injury network" map" is on the page and is used for D7. OK.
- **Claim verdicts:**
  - D7 (13% / 74%, high-injury network) is "cannot be checked". Correct: it is a citywide share.
  - D8 (eight of nine killed this year) is "cannot be checked". Correct: another area and period.
  - **D6 is wrong in kind.** The claim reads "Mission Street & South Van Ness Avenue had 48 injury crashes in police records since 2021-10-31", verdict "consistent with the record". **The source never says 48 or anything like it.** The agent took its own record number (receipt D3), wrote it up as a claim, checked it against the same receipt and published "Claim verdict consistent with the record". The check is circular, and a reader of the report's claims table will think Walk SF made a claim that the record confirmed. This is the spirit of failure type 3 ("consistent" for a number that was not really tested).
- **Record check (mine):** DataSF `ubvf-ztfx` (now served from data.sf.gov) gives **49** injury crashes and **0** killed within 100 m of (37.77305, −122.41862) since 2021-10-31. The tool says 48 and 0. Consistent.
- **Unreconciled death.** The source being checked reports a pedestrian **killed** at this corner on 2026-04-13, inside the window. The finding and the letter say "0 people were killed" and never mention the mismatch. I checked:
  - The injury dataset holds a 2026-04-13 01:53 crash at "MISSION ST / SOUTH VAN NESS AVE", coded "Injury (Complaint of Pain)" with `number_killed = 0`.
  - The city's fatality dataset `dau3-4s8f` (latest row 2026-08-07) has no Mission/SVN entry. It does hold Walk SF's other 2026 deaths (Bayshore/Silver, Bayshore/Arleta, 4th/Channel, Mission/Naglee, …).

  So the record does say 0. But a letter sent on the strength of this press release would tell the agency "0 people were killed" at a corner where the press release reports a death. The desk should flag this as "the source reports a death the record does not yet hold"; it is exactly what a reader needs to know.
- **Letter problems:**
  - The salutation is garbled: "Dear colleagues at SFMTA and route designation only; confirm ownership,". Text meant for the owner field leaked into the greeting.
  - It states as fact: "**the current yellow plus all-red time is below the ITE recommended practice**". None of the cited sources (injury crashes, crosswalks, painted safety zones, CMF 1410/4219, BCA guidance) contains signal timings. This is an untested fact in a letter labelled "drafted and checked". In run 3 the same text appears as something to check ("…and whether the current yellow plus all-red time is below…"), so the drafter is turning a check item into a claim.
  - "48 crashes, of which 48 were injury crashes": harmless, because the dataset holds only injury crashes, but it reads oddly.
  - "The earlier program's effect was not shown, so we ask for a different approach." That is a non-sequitur. A citywide estimate of +4% (−25% to +33%) is "not shown", not evidence against crosswalks.
- **D4 ownership finding:** "SFMTA is responsible for 12th Street, Chase Court, Colusa Place, Lafayette Street, Otis Street". These are side streets inside the buffer, none of them the corner's streets. Mission Street, an ordinary city street at this point, is not assigned to SFMTA. Only South Van Ness (US 101) is plausibly state-owned. This finding is not useful and partly wrong.
- **D9 overstatement:** "repeating it here is not supported by the city's own record" goes beyond "could be zero".
- **Privacy:** no names or plates. The page names a different victim (Cuthberto Zamora); the output does not repeat it. OK.

### 2.2 ind_url_dc — `runs/checks/20261103-131441_north_capitol_street_new_york_avenue_nor/`

**Source** (https://wjla.com/news/local/metropolitan-police-department-mpd-northeast-dc-hit-and-run-north-capitol-street-new-york-avenue-…), as I read it:
> "Fifth District officers responded around 6:51 p.m. to the intersection of North Capitol Street and New York Avenue NE for a reported traffic crash. Police said a woman was struck by an occupied vehicle. The vehicle fled the scene and was later found unoccupied nearby."

- **Corner:** "North Capitol Street & New York Avenue Northeast". Correct.
- **Quotes:** all four are on the page word for word: "A woman died after she was struck by a vehicle that fled after a crash in Northeast D.C." / "Police said a woman was struck by an occupied vehicle." / "The vehicle fled the scene and was later found unoccupied nearby." / "She was unconscious but breathing when she was taken from the scene, police said."
  - **But none of them names the intersection.** The finding "…at North Capitol Street and New York Avenue NE" cites the URL, yet the one sentence that places the crash there ("Fifth District officers responded … to the intersection of North Capitol Street and New York Avenue NE") was not quoted. The corner is right, but the evidence offered for the corner is not the evidence that establishes it.
- **Claims:** none. The article has no statistics, so that is acceptable.
- **Record check (mine):** DCGIS Crashes `MapServer/24` within 100 m of (38.9073, −77.0090) holds 91 injury or fatal crashes since 2021-10-31, against the tool's 99 (my injury definition differs). It includes **a FATAL_PEDESTRIAN = 1 crash on 2026-08-16 23:10 UTC at "1 NEW YORK AVENUE NW"**, which is this crash. The tool's "1 person killed" is right, but it never links that death to the source's crash, which would have been the useful finding.
- **The letter is promised but missing.** The summary says "investigated against city crash records **with request letter drafted**", and finding D5 says "A request letter … is ready to draft". But `letter` is `null`, the report has no letter section, and `investigate` was called with `draft_letter: true`. Published text claims an output that does not exist.
- **Ownership:** "New York Avenue … listed as **state transportation department** responsibility by route designation only". DC has no state DOT apart from DDOT, which serves as both. Addressing a letter to "DDOT and the state transportation department" (finding D5) is wrong for DC. The registry needs a rule that the "state" owner is the city agency for DC.
- **D2 overstatement:** "This corner got Leading Pedestrian Interval signals in 2017. … at 267 sites the change in pedestrian injury crashes (−19%, 95% interval −35% to +1%) could be zero. Repeating it here is not supported by the city's own record." An interval of −35% to +1% leans clearly toward benefit. Calling that "not supported" misreads it, and nobody proposed "repeating" an LPI that is already there.
- **Privacy:** no names or plates. OK.

### 2.3 ind_false_statement — `runs/checks/20261103-131615_atlantic_avenue_flatbush_avenue_brooklyn/`

- **Status:** published. Claim D6, "Atlantic Avenue & Flatbush Avenue in Brooklyn had zero injury crashes in the last five years", gets the verdict **"differs from the record"** with the reason "0 is not the record's number of injury crashes". It is quoted from `input:text` and marked verified. **This matches the expectation.**
- **Corner:** Atlantic Ave & Flatbush Ave, Brooklyn. Correct.
- **Record check (mine):** NYC `h9gi-nx95` within 100 m of (40.68410, −73.97751) holds **92** injury crashes, 251 crashes in all, 23 pedestrians and 9 cyclists injured, and 0 killed. The tool says 75 injury crashes, 221 in all, 20 pedestrians, 9 cyclists and 0 killed. The verdict is safe either way. The tool's injury count is about 18% below a plain 100 m count, perhaps because of de-duplication or snapping to the node; I could not check this because the D3 receipt data is not saved.
- **Letter:**
  - "Leading Pedestrian Interval was recorded as already in place in **1996**": doubtful, since NYC's LPI programme is much later. This looks like a date-field artefact.
  - "The latest recorded safety project at the junction was Flatbush Ave and Atlantic Ave in 2018" names the project by its location, which tells the reader nothing.
  - The longer-yellow bullet is garbled ("which needs a site check … and whether the current yellow plus all-red time is below the ITE recommended practice and is expected to prevent…").
- **Other findings:** truck/bus 35% against 16%, plausible on bus routes by Atlantic Terminal. I did not verify it. Council District 35 and Brooklyn CB2 are plausible.

### 2.4 ind_true_statement — `runs/checks/20261103-131747_milwaukee_avenue_division_street_chicago/`

- **Status:** published. Claim D6, "Police records show 66 injury crashes … in the five years to October 31, 2026", gets **"consistent with the record"**, quoted from `input:text` and verified. **This matches the expectation.**
- **Record check (mine):** Chicago `85ca-t3if`, `injuries_total > 0`, within 100 m of (41.90338, −87.66710): **64** (50 m: 40; 75 m: 54; 150 m: 85). The tool's 66 is plausible. The expected value 66 is identical to the tool's own count, though, so this row only shows that the tool agrees with itself. It does not show that the count is right. A true-statement control should use a number derived independently (for example the city's own published figure).
- **Letter:** it lists Ashland, Bosworth, Milwaukee and Division, which is correct for the Ashland/Milwaukee/Division six-way. Two signal fixes are given break-even costs. I have nothing further to object to.
- **Minor:** "What these crashes have in common is not compared with the rest of the city: the location has no screened priority junctions to compare against." This is fine, but it means Chicago gets no pattern analysis at all.

### 2.5 proposals #8 chicago_1e736f — `runs/reviews/20261103-132119_ridge_avenue_hollywood_avenue_chicago/`

**Source** (https://chicago.suntimes.com/transportation/2026/09/28/chicagos-first-pedestrian-hybrid-beacon-accessible-signals-edgewater-intersection-2021-crash, read via WebFetch), as I read it:
> "The $1.3 million project will bring a first-in-the-city pedestrian-activated 'hybrid beacon'…"; "The overhaul will streamline the five-way intersection into a standard four-way design."; the intersection "currently has no traffic signals"; "about five years after a pedestrian died in a 2021 crash at the intersection."

- **Faithfulness of the proposal row:** it is mostly faithful, but "pedestrian hybrid beacon … about $1.3 million" attributes the whole budget to the beacon. Per the article, the $1.3M also buys a **geometric realignment from five legs to four**, accessible pedestrian signals, new crosswalks and signs, and resurfacing and landscaping. A PHB alone typically costs a fraction of that.
- **Corner:** Ridge Ave & Hollywood Ave, Chicago. Correct.
- **Registration:** "Pedestrian Hybrid Beacons". Correct for the beacon, but **the realignment, which is the larger engineering element, is not registered or appraised at all.**
- **`appraisal.site_control = "Signalized"` is wrong.** The article says the intersection "currently has no traffic signals". The Chicago crash records within 100 m mix "TRAFFIC SIGNAL" (73) with "NO CONTROLS" (61) and "STOP SIGN/FLASHER" (13). The signalised crashes cluster on the 5679–5700 block of Ridge, probably a neighbouring signal, so the buffer is pulling in another junction's control type. The memo then says "no PHB effect can be estimated **for this signalized site**".
- **Alternatives are physically impossible.** The "best alternative" is a Leading Pedestrian Interval (break-even $313k), and the letter also asks for reflective backplates on the traffic signals. **Neither can exist at an unsignalised intersection.** A transport engineer would reject the memo on this point alone.
- **Verdict logic:**
  - The reason ("CMF 10608 was measured only at higher-speed roads like the Arizona study sites") is a defensible caution on transferring the CMF.
  - The finding "The $1,300,000 proposal cost far exceeds the $313,000 break-even **for the best alternative**" compares the proposal's cost with an alternative's break-even, which is meaningless. The memo summary then turns it into "the $1300000 cost exceeds expected value", but no expected value for the PHB was computed (`proposed: null`).
  - With about 1 pedestrian injury crash a year (my count: 4 pedestrian-type injury crashes in 5 years within 100 m; 24 injury crashes against the tool's 23) and a 2021 death, a sensible verdict would be "proceed only after a site check" or "compare before committing", with the realignment appraised. "Reconsider" for these reasons is not supportable.
- **Red team:** both objections echo the verdict:
  - O1: small target pool, answered "Agreed".
  - O2: CMF does not transfer, answered "Agreed".

  Neither tests the verdict's own assumptions (the signal status, cost attribution, the realignment). The answers restate; they do not engage.
- **Letter:**
  - Salutation garbled again: "Dear colleagues at route designation only; confirm ownership and CDOT,".
  - It assigns North Ridge Avenue to "the state transportation department (route designation only)". I could not confirm that Ridge is a state route; to my knowledge it is a CDOT arterial. Unverified.
- **Privacy:** the article names the 2021 victim; the memo does not. OK.

### 2.6 proposals #9 dc_aa16ac — `runs/reviews/20261103-132405_23rd_street_northwest_l_street_northwest/`

**Source** (https://anc2a.org/wp-content/uploads/2026/05/23L-Draft-Resolution.pdf), page 3, residents' letter:
> "The underlying issue appears to be unprotected left-turn movements occurring simultaneously with pedestrian walk signals … Request consideration of a protected left-turn signal phase … Support implementation of a leading pedestrian interval (LPI) or other pedestrian-priority signal timing measures"

- **Faithfulness of the proposal row:** faithful in substance. Note that the LPI and protected-left requests come from the **residents' attached letter**. The ANC resolution itself asks only for an "expedited traffic safety review" of 23rd & L and 22nd & L.
- **Corner:** 23rd St NW & L St NW. Correct.
- **Registration: wrong, because it is incomplete.** `proposal.countermeasure = "Leading Pedestrian Interval"`. **The protected left-turn phase was dropped**, although it is the treatment aimed at the stated problem (drivers turning left into people crossing).
- **The in-place fact is correct.** The DDOT TrafficSafety `MapServer/1` row "23RD ST AND L ST, NW" has `LPI_Y_OR_N = "Y"`, `ImplementationCompletionDate = "FY20"` and a config revision of 2019-11-08.
- **Verdict:** "reconsider: LPI already installed". That is right for the LPI half and wrong as a verdict on the proposal. An engineer reads "LPI already there and pedestrians are still being hit by left-turners" as the textbook case for a protected (or lagging, or restricted) left turn. The tool turned the strongest argument for the second half of the proposal into a "reconsider".
- **Record check (mine):** DCGIS within 100 m gives 17 injury or fatal crashes, but 9 of them geocode to "2201 L STREET NW" (the 22nd St end of the block). Within about 50 m of 23rd & L the record is consistent with the tool's 8 injury crashes, 1 pedestrian injured, 2 cyclists and 1 killed. **The one death is a pedestrian: FATAL_PEDESTRIAN = 1 on 2026-04-18 at "1100 23RD STREET NW"**, which is the crash in the ANC letter.
- **Red team:**
  - O3, "Only one pedestrian injury among eight injury crashes limits potential benefit of a pedestrian-turn fix", is answered "Agreed, … limiting scope for a pedestrian-turn fix". **That answer ignores the pedestrian killed at this corner in the same record (1 killed).** It is wrong on the receipts it cites.
  - O2, citywide LPI "could be zero", is answered "Agreed", accepting the same overreading of a −35% to +1% interval as in run 2.
  - O1 restates the verdict; O4 restates a finding; O5 is procedure ("needs DDOT"), not an objection.
  - All five agree with the verdict; none tests it.
- **Letter:**
  - "The latest recorded safety project is Local Sidewalk Restoration Citywide Maintenance (**2032**)". The date is in the future and the item is maintenance, not safety work.
  - It repeats "**the current yellow plus all-red time is below the ITE recommended practice**" as fact, with no source.
  - It contains the junk sentence "Records count injured by mode as cyclist, motorist, and pedestrian and killed by mode as cyclist, motorist, and pedestrian."
  - "Please take a different approach rather than repeating it here": nobody asked to repeat it.
  - "This location is a city priority location under the city's high injury network" sits beside the finding "No crash pattern here stands out".
  - The letter never mentions left turns, which are the residents' whole complaint.
- **Privacy:** the PDF names the victim and a resident with her e-mail; neither appears in the output. OK.

### 2.7 proposals #10 nyc_22c137 — `runs/reviews/20261103-132722_west_21st_street_10th_avenue_new_york_ci/`

**Source** (https://cbmanhattan.cityofnewyork.us/cb4/wp-content/uploads/sites/10/2025/12/25-TPC-Letter-to-DOT-re-W.-21st-Street-and-10th-Avenue-Intersection.pdf), as I read it:
> "Bike lane pedestrian islands: the islands have not been built in concrete and therefore provide no protection for pedestrians or children from the fast-moving traffic on the avenue. In the near term, we ask that you install concrete islands in every intersection along the bike lane. In the immediate term, please add physical protections to this and other painted pedestrian islands…"

- **Faithfulness of the proposal row:** faithful, though it narrows "every intersection along the bike lane" to this one. The letter's other two requests (re-striping the high-visibility crosswalk on the west side, and larger wrong-way signs) are not in the row. That is acceptable, since the row is one proposal.
- **Corner:** West 21st St & 10th Ave. Correct.
- **Registration:** "Medians and Pedestrian Refuge Islands in Urban and Suburban Areas". Correct. These are bike-lane buffer islands on a one-way avenue, the closest PSC match.
- **Record check (mine):** NYC within 100 m of (40.74640, −74.00511) gives **44 crashes, 10 injury crashes, 5 pedestrians and 3 cyclists injured, 0 killed**. The tool's 44, 9, 5, 3 and 0 match well.
- **Verdict:** "reconsider: … its CMF Clearinghouse records are for uncontrolled sites, and this site's control is signalized". This follows the documented rule ("no evidence fits the site"). As engineering judgement it is too strong:
  - Missing CMF evidence is not evidence against the fix.
  - Converting paint to concrete is a low-cost hardening of geometry that already exists.
  - Five pedestrians were hurt in 5 years, and the board reports drivers driving through the painted islands.

  "Proceed only after a site check" would be the defensible output. A rule that turns "no applicable CMF" into "reconsider" will turn down most hardening projects at signalised junctions.
- **Red team:**
  - O1 (CMF does not apply) is answered "Agreed", a restatement.
  - O2, "pattern is passing too closely … not pedestrian refuge need", is answered "Agreed … the proposal does not match the corner's pattern". **This is arguably wrong.** "Passing too closely" at 23% against 3% is consistent with drivers squeezing past or through the painted islands and the bike lane, which is exactly what hard islands address. The answer accepts the objection without thinking about it.
  - O3, "Site check required for signal alternatives shows proposal precondition missing", is incoherent: a site check for *alternatives* has nothing to do with the proposal's preconditions. The answer ("the signal alternatives still need a site check") **does not address it**. It just restates a different fact.
  - O4 (ownership) is answered "Noted". Fine.
  - O5 (an alternative has a break-even, the proposal has none) is answered "comparison favors review of alternatives". This **dodges**: having a number is not having a better number. It does not say whether 0.1 crash a year from longer yellows beats hard islands.
- **Letter:** **the letter does not mention concrete islands at all.** It asks NYC DOT for backplates (0.3 crashes a year) and longer yellows (0.1 crashes a year) instead. For a community-board request this quietly swaps the board's ask for the tool's. "The last recorded safety project at this location was a Leading Pedestrian Interval signal in 2019. Even with that work in place, crashes continue" is fine. Council District 3 and CB4 are correct.

## 3. Overall assessment

**What held up**
- **Corner identification** was right in all 7 runs, including a messy press release, a long news URL, a three-street (Ashland, Milwaukee, Division) intersection and a five-way intersection.
- **Quote verification** was honest. Every quote marked `verified` (8 from two web pages, 2 from input text) is on its page word for word, apart from curly versus straight quote marks. Nothing was invented.
- **The two control statements** got the right verdicts: "differs" for the false zero, "consistent" for the true 66.
- **"Cannot be checked"** was applied correctly to citywide shares and this-year counts.
- **Crash counts** match my independent re-counts within method noise for all 7 corners: SF 48 vs 49, Chicago 66 vs 64, NYC 10th Ave 9 vs 10, Chicago Ridge 23 vs 24. NYC Atlantic is lower, 75 vs 92.
- **Privacy:** none of the outputs contains a victim name, a resident's name, an e-mail address or a plate, although three sources contained them.
- **In-place detection:** the DC LPI (FY20 / 2019) is real.
- **Cost:** low and as advertised, $0.03–0.06 Meta per run.

**What did not hold up**
- The review path's understanding of a proposal: components are dropped, site control is wrong, and costs are misattributed.
- The letters: they are labelled "checked" but carry untested or false statements and template debris.
- The red team, which only ever agrees with the code's verdict.
- Run artefacts that cannot be audited: the receipts D1–D5/D7 in `result.json` hold no data, so a reviewer cannot check "a number is not in the receipt it cites" from the saved run.

**The three most important problems, ranked**

1. **The review registers and appraises the wrong project, then sets a confident verdict on it.**
   - #9 dropped the protected left-turn phase, the treatment that fits the residents' complaint, and said "reconsider" because the *other* half (LPI) is already there.
   - #8 called an unsignalised intersection "Signalized", proposed LPI and signal backplates where there is no signal, ignored the realignment that makes up most of the $1.3M, and compared the proposal's cost with an *alternative's* break-even.

   **Fixes:**
   - Register every countermeasure in a proposal and appraise each one.
   - Take site control from the source or the city's signal inventory, not from crash-report control codes in a 100 m buffer.
   - Never recommend signal-only treatments at an unsignalised site.
   - Ask for a cost split, or flag "cost covers more than this countermeasure".
   - Never compare a cost against another option's break-even.

2. **Letters and summaries marked "drafted and checked" contain unchecked or false content.**
   - "The current yellow plus all-red time is below the ITE recommended practice" is stated as fact in #1 and #9, with no timing data cited.
   - A "2032" project is cited in #9.
   - "0 people were killed" in #1 sits beside a source reporting a death at that corner, with no note.
   - A "state transportation department" appears in DC (#2, and a state owner of Ridge Ave in #8).
   - The summary says a letter was drafted when `letter` is null (#2).
   - Two salutations read "Dear colleagues at … route designation only; confirm ownership".
   - One letter drops the proposal it was meant to support (#10).

   The number gate seems to check numbers only. It needs to check categorical facts, dates (no future dates), owner logic per city, and that the summary matches the output.

3. **The checks confirm themselves rather than test anything.**
   - In #1 the agent wrote its own record count up as a source "claim" and published it as "consistent with the record". The checker should refuse claims whose text is not in a source.
   - In all three reviews every red-team objection backed the code's verdict, and the answers are "Agreed" plus a restatement. One answer is wrong on its own receipts (#9 O3 ignores the pedestrian death in "1 killed"), and two dodge (#10 O3, O5).
   - "Could be zero" on an interval of −35% to +1% is turned into "repeating it here is not supported" (#2, #9).

   Prompt the red team to attack the verdict's assumptions, not only to agree with them, and reword null programme results as "not shown either way". Also save each receipt's data in `result.json` so third parties can audit numbers without rerunning.

## 4. Totals

| run | folder | Meta $ | Muse Spark Open $ | seconds |
|---|---|---|---|---|
| ind_url_sf | runs/checks/20261103-130945_mission_street_south_van_ness_avenue_san | 0.0645 | – | 141.3 |
| ind_url_dc | runs/checks/20261103-131441_north_capitol_street_new_york_avenue_nor | 0.0335 | – | 282.7 |
| ind_false_statement | runs/checks/20261103-131615_atlantic_avenue_flatbush_avenue_brooklyn | 0.0338 | – | 75.3 |
| ind_true_statement | runs/checks/20261103-131747_milwaukee_avenue_division_street_chicago | 0.0313 | – | 72.2 |
| #8 chicago_1e736f | runs/reviews/20261103-132119_ridge_avenue_hollywood_avenue_chicago | 0.0261 | 0.0215 | 198.2 |
| #9 dc_aa16ac | runs/reviews/20261103-132405_23rd_street_northwest_l_street_northwest | 0.0299 | 0.0216 | 142.7 |
| #10 nyc_22c137 | runs/reviews/20261103-132722_west_21st_street_10th_avenue_new_york_ci | 0.0289 | 0.0278 | 170.7 |
| **total** | | **0.2480** | **0.0709** | **1,083.1 (18.1 min)** |

- Wall clock: 19:07 to 19:27 (+06) for the 7 runs, done one after another. No run failed, hung or was retried.
- Grades: **PASS 2, PARTIAL 3, FAIL 2.** Both FAILs are in the pre-commitment review, the part a funding decision would rest on.
