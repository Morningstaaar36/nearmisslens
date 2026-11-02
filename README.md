# NearMissLens

**A street-safety desk run by Meta's models and refereed by code.** Give it something real: a news report of a crash, an official's claim that a safety program worked, a resident's 311 report with a photo, a corner, or a whole city. Muse Spark plans the work and chooses every step.
- It finds and reads the source on the live web with Meta's `web_search`.
- It loads the city's open datasets with tool search.
- It investigates the intersection with checked tools.
- It tests the city's programs against the city's own crash record.
- It ranks fixes by the strength of their evidence and finds who owns the road.
- Muse Spark Open drafts the letter.

Nothing is published until code has checked every number against the record and every quote against its page.

**On 12 fresh real cases (T21c, registered before it ran), the desk published 11, and all 25 of their quotes were found on the page they cite. It cost $0.126 a case on the Meta API.** The first version published 4 of 12. What we changed in between, and what a review of the published cases still found wrong, is below.

**Open it:** [morningstaaar36.github.io/nearmisslens](https://morningstaaar36.github.io/nearmisslens/). It has the live desk's cases, with every step the agent took, plus each city's action plan: New York's 304 Vision Zero priority intersections and the 50 worst crash locations in each of Seattle, Washington DC and San Francisco, found from their own crash records. No key or install is needed.

![New York's action plan: the largest low-cost estimates add up to 338 fewer crashes a year, the evidence supports 86; tiles for harm, supported corners, road owners, turn calming and denied requests, then the corners where a fix was asked for and turned down](docs/img/plan_nyc.png)

## One real case, end to end

The input was one sentence: *find a news report from the last two weeks about a pedestrian or cyclist hit at a named intersection in New York City, investigate it, check what it says and draft the request letter.*

1. **The source.** Muse Spark searched the web and found Streetsblog's report that a sanitation truck driver killed a pedestrian crossing Bay Parkway at Cropsey Avenue on October 29, 2026. It read the page with `read_page`, and both published quotes were found on it.
2. **The corner.** `investigate` built the corner's case from NYPD records:
   - 51 injury crashes in five years, with 19 pedestrians and 3 cyclists injured;
   - turn calming here in 2021, a program whose citywide drop began before the work, so it cannot be credited;
   - leading pedestrian intervals as the fix the city's own record supports;
   - NYC DOT as the road owner.
3. **The claims.** The article says at least 106 crashes injured 77 people there since 2021. The record within 100 m over five years has 113 crashes, so the article's count is for another area or period. The desk now says "differs from the record" and states the record's frame. It does not say "false".
4. **The letter.** Muse Spark Open drafted the letter to NYC DOT, copied to the council member and community board, and code checked every number in it.
5. **The gate.** The draft passed on the first `finish`, after two dry runs with `check_findings`.

Cost $0.076. It took 18 minutes, nearly all of it waiting for OpenStreetMap's servers. Police crash data lags by days to weeks. The record the desk read did not yet include this death, so the letter's "no deaths were recorded" is true of the record but not of the street; the desk should say so (a limit, below).

## The desk, run after run

Each run is 12 fresh real cases: a news report per city, an official statement per city, and 4 San Francisco 311 reports with photos at high-crash places. Each was registered in [`validation/BENCH_PREREG.md`](validation/BENCH_PREREG.md) before it ran. Every case, every step and every refusal is in `validation/results/bench/experiment_T21*.json` and on the site.

| Run | What changed | Published | Quotes found on their page | Meta $ a case | Rule (at least 9 of 12) |
|---|---|---|---|---|---|
| T21 | first version | 4 of 12 | (the gate refused the rest) | $0.083 | not met |
| T21b | intersections in several written forms; unreadable pages published as unverified | 5 of 12 | 5 of 13 | $0.079 | not met |
| T21c | the failure study's fixes (below) | **11 of 12** | **25 of 25** | $0.126 | **met** |

**What the failure study of T21 and T21b found, and what fixed it.** Each fix is a small adapter around a known model weakness:
- **The model wrote quotes from memory.** For example, it gave a victim's age as 47 where the page says 30. Fix: a `read_page` tool returns the exact text the citation gate checks, and quotes must come from it.
- **Findings cited the wrong receipt.** Fix: `investigate` lists each code-written claim with its receipt, and the gate names the receipt that holds a finding's numbers. It never offers that hint for a finding without numbers.
- **Facts from the source were mixed with numbers from the record.** Fix: a fact from the source cites the source's URL, and its numbers must be on that page.
- **Programs were looked up by city name, not city id, so every program came back "untested".** Fix: the program and city are matched by their words.
- **Geocoding fell back to house numbers and businesses.** Fix: an address goes to the nearest screened corner within 150 m, or is refused, and a case stays on one intersection.
- **The agent probed the gate one sentence at a time until the turn limit.** Fix: `check_findings` dry-runs the whole draft, and claim checks are capped at 6.

**What a review of T21c's 11 published cases still found** (post hoc; the hand audit is pending):
- In 2 cases a claim was called "contradicted by the record" when the record could not test it. Our code had let the model-read check decide a verdict, although T20b measured it refusing about a quarter of true claims.
- In 2 more, "contradicted" was too strong for a source counting another area or period.
- One licence plate printed in a 311 report was read out by the photo reader.

Verdicts are now decided by the number checker alone and state the record's frame, and plates are refused by the gate and redacted on the site. T21d tests this on fresh cases.

## The problem

US cities are spending federal safety money on plans like this one. The Safe Streets and Roads for All program has $5 billion for 2022–2026 and has already awarded "$3.9 billion in Federal funding to over 2,000 communities" ([USDOT](https://web.archive.org/web/20261021072608/https://www.transportation.gov/grants/SS4A)). Its 1,272 action-plan grants for FY22–FY25 had a median budget of about $250,000 (our count from USDOT's award lists, [`validation/ss4a/`](validation/ss4a/)). Every eligible plan must map high-risk locations and explain how projects are prioritized: questions 3 and 6 of the self-certification worksheet.

The estimates behind those choices are easy to get wrong in two ways.
- **A fix is credited with an effect measured somewhere else.** FHWA's CMF Clearinghouse warns that "the characteristics associated with the CMF should closely match the characteristics of the scenario at hand" ([FAQ](https://cmfclearinghouse.fhwa.dot.gov/faqs.php)).
- **A program is credited with a drop that was coming anyway.** Before/after comparisons at high-crash sites are "likely to result in an overestimation of the treatment's effect" ([FHWA-RD-94-082](https://www.fhwa.dot.gov/publications/research/safety/humanfac/94082.cfm)).

Requests can also go to the wrong place: at some corners the city is not the only road owner.

NearMissLens drafts the safety analysis and the project list from public records. A claim reaches the reader only after code has checked it against the record, and our own red team measures how often that check can still be fooled (below).

## What it found

From `nml plan CITY` (validation/results/bench/plan_*.json), records as of 31 October 2026:

| | New York | Seattle | Washington DC | San Francisco |
|---|---|---|---|---|
| Corners | 303 distinct points among the 304 priority intersections | 50 worst | 50 worst | 50 worst |
| Harm a year, each crash counted once (U.S. DOT injury-crash value; deaths not valued separately, so this is low) | $786 million | $183 million | $192 million | $129 million |
| Largest low-cost estimate at each corner, added up | 338 crashes a year | 109 | 76 | 58 |
| Supported without a site visit | **86** at 129 corners; **83** with each crash counted once, **79** after regression to the mean | **8** at 8 corners (6 counted once) | **2** at 5 corners | **0** |

The gap between the last two rows is the point. In New York the largest estimate at 270 of the corners is signal backplates, which hold only where the record shows red-light entries; elsewhere they need a check nobody has made. Yellow timing needs a timing check, and the only crosswalk study in the set was done at school crossings.

What the evidence supports now:
- **leading pedestrian intervals at 83 corners**, a fix the city's own past installs passed the causal gate on;
- **backplates at 44 corners**, where FHWA's cited study fits the record;
- **rectangular rapid flashing beacons at 2** uncontrolled crossings.

In Seattle most estimates rest on a pavement-friction study whose sites were chosen for low friction, which the crash record cannot show, so they need a site check too. San Francisco's records support no low-cost estimate without a site visit.

**New York, also from the same cases:**
- **Who must act.** The city's transportation department is not the only road owner at 12 corners: the state DOT at 11 and MTA Bridges and Tunnels at 1. Each agency gets its own letter, number-checked like every claim.
- **Programs the record does not back.** 54 corners already got turn calming. Its citywide drop began before the work, so the engineer flags it before the same thing is proposed again.
- **Asked for and turned down.** At 19 corners, a leading pedestrian interval was requested and denied (2004–2016, NYC study requests w76s-c5u4). None is recorded in the city's open datasets there now, and pedestrians were injured there in the records since 2021. The city has since installed thousands of leading pedestrian intervals elsewhere (1,651 in the window our causal gate measured), so these corners stand out. Ryan E. Kelly found that leading-interval and left-turn requests in Queens Community Board 5 had a 0% approval rate over five years ([2026](https://junipercivic.com/?p=19593)); here each denial is tied to a priority corner and to the injuries in its five years of records.

## Who would use this

- **A city or a consultant writing an SS4A action plan:** the high-risk map and the prioritized project list with the evidence behind each fix (worksheet questions 3 and 6), as a page and a CSV, for any city with open crash data. It is meant to replace the pulling of records and looking up of CMFs, not the engineer's site visit.
- **A community board, council office or advocacy group:** a corner's case in plain language, and a letter addressed to the agency that owns the road, with every number checked. In New York that includes the 19 corners where a fix was asked for and turned down.
- **A city's own safety team:** which of its programs the record backs (leading pedestrian intervals) and which it does not (turn calming), before the same program is proposed again.

## One corner: Bruckner Boulevard & Hunts Point Avenue

The worst of the 304:
- **The record.** 129 injury crashes in five years: 29 pedestrians and 3 cyclists injured. That is about $8.8 million a year at the U.S. DOT's values.
- **What the crashes have in common.** A truck or bus was involved in 28% of its 310 police-reported crashes, against 16% at the other priority corners. "Following too closely" was recorded in 12%, against 6%. Both survive a correction for testing many patterns, and the truck share held up on later years the analysis never saw. The corner sits beside the Hunts Point Food Distribution Center; police records cannot say why the share is high.
- **The fix, by evidence.**
  - Reflective signal backplates: about 3.9 fewer injury crashes a year, $1.3 million (CMF 1410, the study FHWA's fact sheet cites).
  - Longer yellow plus all-red time: about 2.0 a year, but only if a timing check shows the current interval is below ITE practice. All four eligible records come from one study (NCHRP Report 705) at signals with short intervals. FHWA's own page cites lower-rated records (380/384, 8–14% fewer crashes), which the code's three-star rule leaves out.
- **Who must act.** The state DOT (Region 11) owns the Bruckner Expressway (I-278) and the Sheridan Boulevard (NY 895), according to the state road inventory. The surface streets are not in that inventory, so they are presumed the city's. Council District 17 and Bronx Community Board 2 can push for the work.
- **What the city's data does not show.** The city's open datasets record no safety work here since a 2015 street project. But New York State's Hunts Point access project improved this intersection in its first phase, completed in 2022 ([announcement](https://www.governor.ny.gov/news/governor-hochul-announces-completion-phase-one-17-billion-hunts-point-access-improvement)). A request to the state should start from that project.

![The case for Bruckner Boulevard & Hunts Point Avenue: each sentence followed by the receipt it rests on](docs/img/copilot_bruckner.png)

## How it works

```
real input: news report | official claim | 311 report + photo | a corner | a city
   |
DESK  Muse Spark 1.3 (Meta Model API, Responses, low effort) plans and chooses every step
   |-- web_search (Meta)        find the source                     -> citation gate: quote must be on the page
   |-- read_page                the page as the gate reads it
   |-- tool search              the city's datasets, one deferred tool per registry entry, each returning its query
   |-- investigate              the engineer's checked tools (below)  -> receipts D1, D2, ...
   |-- check_claim              a source's number against a receipt  -> verdict saved as a receipt
   |-- program_record           the causal gate's verdict on the program the source credits
   |-- view_photo               Muse Spark reads a 311 photo          -> shown as a model observation
   |-- draft letter             Muse Spark Open (Baseten)             -> every number checked
   '-- finish                   publish gate: numbers vs receipts, quotes vs pages, site-check and wording rules
```

The desk follows the LLM-Modulo pattern (Kambhampati et al., 2024): the model generates, sound external critics accept or return structured criticism, and the model revises. The critics are code, never the model grading itself (Huang et al., 2024). The orchestrator's receipts are its ledger (Magentic-One, Fourney et al., 2024).

The engineer behind `investigate` has six tools. Each tool is plain code over public records with a check inside it, and each returns its data with a **receipt**: the datasets it read, the date the records run to, the checks it ran, and the seconds it took.

| Tool | What it reads | The check inside it |
|---|---|---|
| `screen_city` | The city's priority intersections and police crash records | Each crash counted once where junction circles overlap |
| `root_cause` | Crashes within 100 m | A pattern is "over-represented" only after a one-sided binomial test with a Holm correction, at least 10 crashes; the wording is "have in common", never "caused" |
| `test_programs` | Every program a registered study tested in this city, and the projects recorded here | The causal gate (below); a corner that already got a program whose effect was not shown is flagged |
| `choose_fixes` | FHWA Proven Safety Countermeasures and 25 curated CMF Clearinghouse records | A CMF counts only where its study sites match: control, crash group, kind of site, and preconditions; each fix gets an evidence tier (measured here, FHWA-cited, national studies, needs a site check, contradicted here) |
| `who_must_act` | The state road inventory, council and community-board maps | No party without the dataset row behind it; inferred owners are marked |
| `draft_request` | The facts above | Every number in the letter must be the record's value for the words next to it |

The agent finishes by submitting its claims, each citing a receipt. The **finish gate** is built to refuse a claim that (T18 measures how often it fails):
- cites no receipt;
- uses a number that is not the receipt's value for what the sentence names. For example, "29 pedestrians were killed" when 29 were injured, a program's site count borrowed from another program, or "no crashes at night" when the record has 67;
- uses wording the record cannot support ("caused", "proves", "certain to", "led to");
- states a fix that needs a site check as if it were supported.

`nml desk T21c` reruns a registered desk run (`--replay` serves it from the cache). `nml engineer "ADDRESS" --agent` lets Muse Spark Open choose the steps and write the claims (it must call a tool each turn and finish within a turn limit). Without `--agent` the same tools run in a fixed order with claims written by code; that mode needs no model and builds the site.

## The model proposes, code checks

Each Meta model does the part it is good at (reading, searching, planning, drafting, seeing, attacking) and code checks the part it is bad at (numbers, causal credit, citations). Each pairing that changes what is shown is measured; the one that is not (the photo reader) is labelled on the page as a model observation:

| Meta model | What it does | The check | Result |
|---|---|---|---|
| Muse Spark 1.3 with `web_search` and tool search | Runs the desk on real inputs from the live web (T21–T21c) | Publish gate: every number against its receipt, every quote against its page | 11 of 12 fresh cases published, 25 of 25 quotes found on their page, $0.126 a case (T21c, rule met; the first version published 4 of 12) |
| Muse Spark (low effort) | Reads residents' 311 photos on the desk | None beyond refusing dark or unreadable images; shown as "a model observation, not a checked fact" | 4 photos read in T21c; not scored |
| Muse Spark Open (Baseten) | Writes the case for the top corners of 4 cities | Finish gate; rechecked against today's receipts by the number checker and the model-read check | 34 run, 26 finished, 37 refused attempts kept; on the site, 131 claims shown (55 flagged by the model-read check) and 44 struck through by today's stricter checker ($2.95) |
| Muse Spark | Reads each CMF's study record to say where it applies (T19) | The quote must be in the record; scored against hand labels written first | 0.92 accuracy against 0.87 for the structured fields alone (4 more right answers of 75); found 4 limits the hand labels missed, now in the data, though none of the four moves a New York total yet |
| Muse Spark | Reads each claim into checkable assertions: field, value, or "none" (T20, T20b) | Code checks every assertion against the receipt | On a fresh attacker: 1.3% of false claims accepted and 27% of true ones refused, against 10.8% and 51% for the regex checker (registered rule met, T20b) |
| Muse Spark and Muse Spark Open | Attack the finish gate with plausible false claims (T18) | Each attack's spec is checked against the receipt; a patch is frozen before a held-out attacker | The gate as registered let 38% of held-out false claims through; the patched gate 21% (the registered halving was not met) |
| Muse Spark Open | Writes and runs its own analysis code on the city's programs (T12) | Causal gate on held-out sites | Without the gate it missed NYC's LPIs and credited two programs the record does not support; with it, it agreed with the registered studies, but the short designs it chose passed 5 of 20 fake programs, about four times the registered design's rate |
| Muse Spark Open | Proposes crash mechanisms from earlier years (T15) | Holm correction, then one test on later years it never saw | False finds near zero and fewer confirmed than the grid (rule not met); 0.72 distinct mechanisms per corner against the grid's 0.64 from 43 times fewer tests, on a measure added after the grid ran (interval −0.07 to +0.23) |
| Muse Spark Open | Answers free questions about a corner (T17) | Finish gate | Scored by the same checker after the run, so this counts what the checker lets through, not truth (T18 measures that): 0 flagged sentences shown with the gate, 31 without. The price: 38% of questions got no answer that passed |
| Muse Spark | Finds a new city's crash and program datasets | A validator in the tool | Refused two wrong Seattle mappings; found Seattle's LPI layer, which the gate then measured at −33% |
| Muse Spark + SAM 3.1 | Reads the aerial photo of each corner (T16) | SAM 3.1 must confirm Spark's point; scored against city map layers | No better than always giving the more common answer, so it changes no recommendation |
| SAM 3.1, Muse Image | Tracks road users in drone video; draws the top fix | Conflict measures against reference tracks; SAM checks each drawing | Vehicle recall 0.51–0.97 on unseen flights; 13 of 20 drawings pass |

Results that lost to a simpler method are in [`validation/BENCH.md`](validation/BENCH.md), with the rest.

## The causal gate

The gate decides whether a city program reduced crashes, and neither the engineer nor an AI analyst can override it. The design is the comparison-group before/after (Hauer, 1997). The comparison sites are ones the city treated later, as in staggered difference-in-differences (Callaway & Sant'Anna, 2021). A placebo install date 19 months early must show no drop. Measuring its false-pass rate on fake programs follows the placebo-law test of Bertrand et al. (2004). It does not fit the Empirical Bayes model usually used for regression to the mean (Hauer et al., 2002), so the plan measures that separately.

![Each program's effect on pedestrian injury crashes as the causal gate measured it (dot and 95% interval, green when it passed) next to a simple before/after (orange ring)](docs/img/gates_forest.png)

| Program | Simple before/after (all treated sites) | The causal gate |
|---|---|---|
| New York leading pedestrian intervals, 1,651 intersections | −24% | **Passed: −17%** (95% interval −22% to −11%); the placebo shows no change. FHWA's Empirical Bayes estimate is −13% for vehicle–pedestrian crashes (Goughnour et al., 2018); NYC DOT's simple before/after says −18% (2022) |
| New York turn traffic calming, 227 sites | −26% | **Earlier trend:** in the 18 months before the work, crashes were already 22% below what the comparison predicted |
| Seattle leading pedestrian intervals, 371 intersections | −25% | **Passed: −33%** (−52% to −13%), the same design unchanged in a second city |
| Washington DC leading pedestrian intervals, 267 intersections | −31% | **Inconclusive: −19%** (−35% to +1%) |
| New York speed humps (1,008) and San Francisco continental crosswalks (780) | | **No measurable change** (−0.4% and +4%) |
| 200 fake programs (random sites and dates) | credits 8.0% | credits 5.5% (3.1–9.6%), above the 2.5% it nominally allows |

A stricter, calibrated version also requires a program to beat 97.5% of fake programs run through the same design. It cut false passes on 100 fresh fakes from 6 to 3, but no longer confirms the leading pedestrian intervals: New York's effect beats 87% of fakes, not 97.5%. The site shows that rank next to each verdict. Read the interval result as consistent evidence across two cities and published studies, not as proof.

## Red-teaming the gate (T18)

An attacker model reads a real receipt and writes false claims that sound right, each with a spec of the field it misreports. Code checks each numeric spec against the receipt and drops claims whose spec does not check out (257 of the held-out set); causal claims are labelled by the attacker. Muse Spark attacked first; the holes it found were patched, and the patch was frozen and pushed. Then Muse Spark Open attacked with two prompt styles never used in development, on corners never used in development.

| | False claims accepted | Worst type | True claims refused |
|---|---|---|---|
| Development attacks, gate as registered | 82 of 194 (42%) | "none" claims, 31 of 31 | 3 of 113 |
| Development attacks, patched gate | 15 of 194 (8%) | | 4 of 113 |
| Held-out attacks, gate as registered | 104 of 273 (38%) | "none" claims, 52 of 56 | 22 of 190 |
| Held-out attacks, patched gate | 56 of 273 (21%) | "none" claims, 27 of 56 | 30 of 190 |

The patch cut held-out attacks by 46%, short of the registered 50%. One false claim in five still gets past the patched regex gate on a new attacker, mostly claims that something is absent.

**So we let a model read the claims (T20, T20b).** Muse Spark turns each claim into assertions (which receipt field, what value, or "none"), and code checks each one against the receipt; the model never decides whether a claim is true. On the T18 held-out set the registered run failed: it caught 98% of false claims but refused 46% of true ones, mostly through three bugs in our checking code (dates, whole-percent rounding, the confidence level). We fixed those and registered a fresh test on corners and an attacker style never used before:

| T20b, fresh attacker (Muse Spark Open, "advocate" style, corners ranked 31–40, 9 distinct) | False claims accepted | True claims refused |
|---|---|---|
| Regex checker | 17 of 157 (10.8%) | 45 of 89 (51%) |
| Muse Spark reads, code checks | 2 of 157 (1.3%, Wilson 0.4–4.5%) | 24 of 89 (27%) |
| Both | 1 of 157 | 55 of 89 (62%) |

The model-read check beats the regex on both counts here (registered rule met). This style pushed the regex into refusing half the true claims; on the T18 held-out set, after the bug fixes, the model-read check let through 2.6% of false claims against the regex's 20.5%, but refused slightly more true ones (17.9% against 15.8%). Labels check only the numbers, so some "true" claims it refuses carry rhetoric a gate should refuse anyway. After a later review we hardened the code side (every number in a claim must be covered by an assertion; no complement shares; counts exact to rounding). On the same readings that lets through 1 of 157 false claims but refuses 58% of true ones, because the model does not always quote every number (post hoc, in BENCH.md). The site uses it as a second check on agent-written claims; it is not yet strict enough on both counts to be the only gate.

## Try it

```bash
uv sync                                                    # Python 3.12; no extras needed
uv run nml --replay plan nyc                               # the city's plan: totals, tiers, one letter per agency
uv run nml --replay engineer "Bruckner Boulevard & Hunts Point Avenue, Bronx, NY"
uv run nml app                                             # the copilot on http://127.0.0.1:8770
uv run nml --replay pages --city nyc --saved-only          # rebuild the static site in docs/
uv run nml treatments T11                                  # rerun New York's study and its gate
uv run nml --replay selftest                               # offline self-test
```

Each desk run reruns from its registered spec with `nml desk T21c` (paid, live web). Its cached answers replay it offline at the commit it ran, since a later code change changes what the model is shown.

`--replay` reads public records as of the pinned date in `validation/ASOF` and serves model calls from the cache, so these give the same answers without keys or network once the replay cache from the latest GitHub release is unpacked. Keys for live runs go in `.env`: `BASETEN_API_KEY` (Muse Spark Open) and `MODEL_API_KEY` (Meta Model API). Every paid call is cached and logged. The tests run on every push on a fresh clone (`.github/workflows/tests.yml`).

**Cities are data, not code.** Each dataset, district map, road inventory, agency and request log is an entry in [`registry.json`](nearmisslens/data/registry.json). Each CMF's limits are in [`fhwa_psc.json`](nearmisslens/data/fhwa_psc.json), and each study is a JSON file in [`validation/studies/`](validation/studies/).

## How we kept ourselves honest

- **Registration.** The rules of every test are in [`validation/BENCH_PREREG.md`](validation/BENCH_PREREG.md), and every result, including the failures, is in [`validation/BENCH.md`](validation/BENCH.md). Earlier registrations were often committed with their results, so git cannot confirm their order. T18 and T19 were committed and pushed before they ran (commits 89de45b and 28ba1b0), and changes after a run are listed there.
- **Cases are rechecked.** Every saved case is rewritten by the current code and rechecked before the site is built. Agent cases are rechecked against today's receipts, and a claim that no longer passes is shown struck through with the reason.
- **The scoreboard.** Every registered test of the current product, met or not:

  | Test | What it asked | Rule |
  |---|---|---|
  | T12 | Does the causal gate credit fewer fake programs than a naive before/after? | met (5.5% against 8.0%, above its nominal 2.5%) |
  | T14 | Does a calibrated gate control false passes and still confirm the LPIs? | (a) met, (b) not met |
  | T15 | Does a model-proposed search find more confirmed crash mechanisms? | not met |
  | T16 | Does reading the aerial photo improve on a constant answer? | not met in effect: changes no recommendation |
  | T17 | Does the gate cut wrong sentences in free answers? | met (38% of questions then get no answer) |
  | T18 | Does a frozen patch halve a held-out attacker's success? | not met (cut 46%) |
  | T19 | Does Muse Spark read where a CMF applies as well as the structured fields? | met |
  | T20 / T20b | Does model reading plus code checking beat the regex checker? | not met / met |
  | T21 / T21b / T21c | Does the desk publish at least 9 of 12 real cases at no more than $0.25 each? | not met / not met / met |
  | T22 | Does a loop governor make the open-weights agent finish more often? | not met |
  | T21d, T23 | Honest verdicts on fresh cases; Corner Watch on city cameras | registered, results in BENCH.md |

  Earlier tests of the drone-video pipeline (T1–T10) are in BENCH.md; most of their rules were not met, and that pipeline is not part of the product.
- **Results that did not help.** Muse Wonder planning video review, a model review panel, Muse Spark rating video clips, residents' reports in crash prediction, and the aerial-photo site check all lost to simpler methods or changed nothing. They are reported in BENCH.md and not used in the product.

## Limits

- **The desk's verdicts are only as good as its gates.** The gates check numbers, quotes and wording, not whether a finding is the right one to make; the review of T21c found two wrong claim verdicts that passed. Every published desk finding is listed for a hand audit, pending.
- **The crash record lags the news.** Police data arrives days to weeks after a crash, so a crash in the news is often not in the record yet. The desk states the record's as-of date, but a letter can still say "no deaths were recorded" the week of a death.
- **The desk is slow where OpenStreetMap is slow.** Most of a case's minutes are spent waiting for public map servers, not on the model.
- **A screening aid, not a design.** Estimates use the Highway Safety Manual's simple method, one fix per corner, never stacked, and a qualified engineer must review each one.
- **Regression to the mean is measured, not modelled.** The plan's factor (0.95 in New York) compares the worst corners with the rest within the listed corners. Where the corners were picked by the same records (Seattle, DC, SF), it understates the effect.
- **The causal gate is observational.** Cities choose their sites, and 5.5% of fake programs passed it.
- **Police factors are an officer's account.** "Have in common" is a pattern in the record, not a cause.
- **"No recorded treatment" means none in the city's open datasets.** The state's 2022 work at Bruckner is one example of what they miss.
- **Signal control comes from OpenStreetMap.** At 42 of the 304 New York corners the street layout could not be fetched before the deadline (the API limited our requests), so their control is unknown and signal-only fixes are not estimated there. The supported totals are low rather than high for that reason.
- **Matching requests to corners uses street names and the borough.** 255 of 303 corners matched; the rest are left out, not guessed.
- **US cities only so far.** The method needs geocoded crash records, a log of fixes made or denied, a road-owner layer and local crash costs. Bangladesh's police counted 5,084 road deaths in 2021 where WHO estimates 31,578 ([Dhaka Tribune](https://www.dhakatribune.com/bangladesh/381561/who-road-crashes-claiming-young-lives-in)), and no official geocoded record is public, so Dhaka is the next step, not a claim.

## Related work

The causal gate follows road-safety evaluation practice (Hauer, 1997; Gross, Persaud & Lyon, 2010, FHWA-SA-10-032). Its placebo date is a negative-control exposure (Lipsitch et al., 2010), and passing it does not prove parallel trends (Roth, 2022). The agent side is close in spirit to POPPER (Huang et al., ICML 2025), which has agents design falsification experiments. It also responds to evidence that AI analysts' verdicts shift with persona or prompt while their estimates do not (Miao et al., 2026; Alizadeh et al., 2026). The number checker belongs with checking text against relational data (Jo et al., 2019), and attacking it with a model follows Perez et al. (2022). The desk follows LLM-Modulo (Kambhampati et al., ICML 2024): models generate and external, sound critics return criticism. The critics are code, because models do not reliably correct their own reasoning (Huang et al., ICLR 2024). Splitting a claim into checkable parts follows SAFE (Wei et al., 2024) and tool-checked critique (CRITIC, Gou et al., ICLR 2024). The orchestrator with a progress ledger follows Magentic-One (Fourney et al., 2024), and reporting cost next to accuracy follows Kapoor et al. (2024, "AI Agents That Matter"). [`docs/METHOD.md`](docs/METHOD.md) has the longer version.

## Built during the hackathon

Meta Global AI Developer Hackathon, Indie track, "Push the Frontier". Solo entry by Morningstaaar36. Every line was written during the event (Oct 27 – Nov 4, 2026). The first commit, `dc089bf`, is dated Oct 27 (ET), and no earlier code was used. Data and model licences are in [`LICENSES.md`](LICENSES.md), and what is stored about whom is in [`PRIVACY.md`](PRIVACY.md).
