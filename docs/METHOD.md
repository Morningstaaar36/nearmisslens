# Falsification gates: how NearMissLens keeps its agents honest

NearMissLens is a street-safety copilot built from agents on Meta's models. Each agent can propose anything. Every number it states is checked against public data before it is shown, every quote it publishes is checked against its page where the page can be read here, and every causal claim must pass the causal gate. What the gates cannot check is labelled as such: a photo reading is shown as a model observation, a quote from a page that could not be read is marked unverified, and claims the second, model-read check flags are shown with the flag. Our own red team measures how many false claims still get through (T18, T20b). This note describes the gates, the evidence that they work, and where they fall short. Our own results come from `validation/BENCH.md`; published studies are cited by name. The rules of each test are in `validation/BENCH_PREREG.md`, our own record rather than an external registry. Earlier registrations were sometimes committed with their results, so git cannot confirm their order; T18 and T19 were pushed before they ran, and changes made after a run are listed there.

## The idea

Meta's verifiable-agent pattern (`meta-models/legal-agent-workshop`, from the hackathon's verifiable-agents session) puts the checks inside the tools, outside the agent's control, so an agent cannot finish until its work passes them. Those checks compare an agent's claims with the case's documents and ground truth. Road safety needs one more kind of check: a claim about the world, such as "a leading pedestrian interval will cut pedestrian crashes here", cannot be verified by reading a document. It can only be tested against what happened when the city did it before.

A falsification gate is a deterministic test, inside the tool an agent uses to finish, that tries to show a claim is wrong. The claim goes through only if the test fails to break it. NearMissLens has these gates:

| Claim | Gate | Where it sits |
|---|---|---|
| A number in a memo, brief or letter | The number must appear in the official record the agent was given | `context.FactCheck`, inside every `finish` tool |
| "This dataset is the city's crash data, and these fields mean injuries" | The adapter must return real records near a point in the city, with dates that parse and are recent, and injury fields that are numeric | `opendata.validate_crash_adapter`, inside the data agent's tool |
| "This fix works in this city" | The city's own past installs must show the effect in a registered before/after design, and a fake install date before the real one must show nothing | `treatments.gate`, inside the analyst's `commit_design` and `finish` tools |
| "The drawing shows the proposed fix" | SAM 3.1 must find more of the fix's concept in the edited photo than in the original, inside the junction, with every real road user unchanged | `brief.illustrate_fix` |
| "These crashes share a mechanism" | Every pattern the agent proposes is tested, Holm-corrected over all of them, then checked once on later years its tools never show | `miner.agent_arm` (code runs the test after the agent's `propose`) |
| "The aerial photo shows a bike lane here" | SAM 3.1 must find it within 15 m of Muse Spark's point; an attribute acts only if it beats the common answer against city map layers | `sitecheck.decide`, `engineer.site_check` |
| A sentence in an answer to a free question | It must cite a receipt of the corner's case and use that receipt's numbers; "caused" and "failed" are refused | `askeng.ask`, the engineer's finish gate |
| A quote from a web page the desk found | The quote must be on the page as fetched here (or the page is marked unreadable and the quote unverified); at least one quote per case must be verified | `orchestrator.quote_check`, inside the desk's `finish` |
| A fact from the source ("the driver was 52") | Its numbers must be on the page it cites | `orchestrator` gate |
| "The record contradicts this claim" | The verdict comes from the number checker, never from a model; "differs" only when the record holds another value for what the sentence names, with the record's frame stated | `orchestrator.claim_verdict`, saved as a receipt the finding must match |
| A licence plate in a finding, summary or quote | Refused; redacted on the site | `orchestrator.has_plate`, `pages.desk_page` |

## The desk: adapters for known model weaknesses

The desk (`orchestrator.py`) gives Muse Spark 1.3 the planning, searching and reading, and gives code the numbers, quotes and causal credit. Each failure the registered runs exposed got a small adapter, and the next registered run measured it:

| Weakness seen | Adapter | Measured |
|---|---|---|
| Quotes written from memory (a victim's age 47 where the page says 30) | `read_page` returns the exact text the citation gate checks | T21c: 25 of 25 published quotes found on their page (T21b: 5 of 13) |
| A finding cites the receipt next to the one holding its number | `investigate` lists claims with receipt ids; the gate names the receipt that holds the numbers | refused finish calls 28 (T21) → 3 (T21c) |
| Probing the gate one sentence at a time until the turn limit | `check_findings` dry-runs the whole draft; at most 6 claim checks | turn-limit stops 3 (T21b) → 1 (T21c) |
| Geocoding a house number or a business as "the corner" | snap to the nearest screened corner within 150 m, else refuse; one intersection per case | T21c: every case on a named intersection |
| A model-read objection treated as a contradiction (found in review) | verdicts decided by the number checker; model-read objections shown as flags | T21d (registered) |
| A licence plate read out from a 311 photo (found in review) | the photo reader is told not to; the gate refuses plates; the site redacts | T21d (registered) |

What the gates do not check is whether a finding is the right one to make; that is what the pending hand audit is for. T24 measures what reaches the reader when Muse Spark works the same inputs with web search alone.

## The causal gate

The statistics are standard road-safety evaluation (a comparison-group before/after with a placebo date); what is new here is that the design sits inside the tool an agent must pass before a claim is shown. Its input is a dated treatment program from the open-data registry (where and when the city installed something) and the city's police-reported crashes.

1. **Design.** For each treated site, crashes within a radius are counted in the window before and the window after the install month (the install month itself is skipped). The expected count after, had nothing been installed, is the count before times the change at comparison sites over the same months (Hauer's comparison-group method). The comparison sites are sites the city treated later (not yet treated), or, when there are too few of them, the rest of the city away from any treatment. The effect is θ = crashes after ÷ crashes expected; below 1 means fewer crashes than expected. A 95% interval comes from resampling treated and comparison sites (2,000 resamples).
2. **Rule.** The program passes only if the interval for θ is entirely below 1.
3. **Placebo.** The same design runs again with a fake install date 19 months before the real one and 18-month windows that both end before the real install. Nothing was installed then, so any "effect" there means the sites were already changing for some other reason (a trend, or the city picking sites after a bad year). The program passes only if every placebo interval includes 1.
4. **Held-out data.** When an AI analyst chooses the design, it explores on a random half of the sites and commits one design. The gate runs that design once on the other half. The analyst cannot try designs until one passes.

Studies are JSON files (`validation/studies/`), so a city, a program, a radius or a window is data, not code. The same engine ran unchanged on New York, Seattle and the other cities listed in `BENCH.md`.

## What the gates found

**New York's leading pedestrian intervals work.** At 1,651 intersections where the city installed an LPI between 2015 and 2021, pedestrian injury crashes fell 17% (θ 0.833, 95% interval 0.781–0.887) compared with intersections that got one later. The placebo on the same sites shows no change (θ 1.02, 0.95–1.10). The national CMF FHWA cites for LPIs (CMF Clearinghouse 9918) is a 13% cut, so the city's own record supports the ranking.

**New York's turn calming shows an earlier trend.** A simple before/after credits it with a 26% cut. The comparison-group estimate is 16%, but in the 18 months before the work started crashes were already 22% below what the comparison predicted (interval 0.70–0.86), so the decline was already under way. The gate does not credit it.

**The LPI result replicates in Seattle.** The same design, unchanged, on Seattle's 371 usable LPI intersections: pedestrian injury crashes fell 33% (θ 0.675, 0.476–0.875) compared with intersections treated later; both placebos include 1. Seattle's crash records count pedestrians involved rather than pedestrians injured, so the outcome there is injury crashes with a pedestrian involved.

**The loop runs without hand wiring.** Given only the city, the program agent found Seattle's LPI layer in the public catalog, chose the install-date field and an 'Existing' status filter, and its validator accepted the mapping on the first try; it turned down 39 other layers. The gate on that agent-found program: −33.0% on 366 intersections (θ 0.670, 0.480–0.872), passed. Its validator refused Seattle's bike facilities because 60% or more of their install dates fall on 1 January or 31 December (year precision).

**The gate rarely credits programs that do not exist.** 200 fake programs were built from New York's injury-crash hotspots, each with 300 sites more than 150 m from any recorded treatment and a random install month. Nothing was installed, so every claimed reduction is false:

| Analysis | Fake programs credited with a reduction |
|---|---|
| Naive before/after | 16 of 200 (8.0%, 95% interval 5.0–12.6%) |
| Comparison group without the placebo | 12 of 200 (6.0%, 3.5–10.2%) |
| Full causal gate | 11 of 200 (5.5%, 3.1–9.6%) |

The registered rule (the gate below the naive rate, with an upper bound of at most 10%) was met. The gate's rate is still higher than the 2.5% a one-sided 95% interval promises, so a passed gate is strong evidence, not proof. On random dates, crash trends partly cancel out, which is why the naive rate is not higher; on the real programs above, where sites were chosen by the city, the naive analysis overstated the LPI effect and credited turn calming.

**An AI analyst with and without the gate.** Muse Spark Open, given blinded programs, wrote and ran its own analysis code (staggered difference-in-differences with site and month fixed effects, mostly) in a sandbox with no network.

| | Without the gate | With the gate (design chosen on half the sites, decided on the other half) |
|---|---|---|
| 20 fake New York programs | 2 credited with a reduction | 4 credited with a reduction and 1 with an increase |
| New York LPIs | "no evidence" (missed) | "reduced", −15.5% |
| New York turn calming | "reduced", −9% | "no evidence" |
| New York speed humps | "reduced", −11% | "no evidence" |
| DC LPIs | "increased", while reporting −15% | "no evidence" |
| Seattle LPIs | "reduced", −17% | "reduced", −47% (held-out half) |
| SF crosswalks, NYC enhanced crossings | "no evidence" | "no evidence" |

With the gate, its verdicts on the real programs matched the registered studies. On fake programs it did worse: all five false passes came from short designs the analyst chose (a 30 m radius and 12- or 24-month windows) on half the sites, where the gate's bootstrap interval is too narrow.

**Testing the tester (T14).** We then registered a calibrated gate. It keeps the original checks and adds one: the program must beat 97.5% of 200 fake programs of the same size, run through the same design in the same city. On 100 fresh fake programs, it passed 3 (T11's design) and 2 (the short design), against 6 and 3 for the original gate. It also failed the registered power check, because it does not pass New York's or Seattle's LPIs: New York's effect ranks at the 7th to 15th percentile of fake programs, depending on the run. Under the rule written beforehand, the original gate stays. The copilot now shows every program's rank among fake programs next to the gate's verdict, wherever the city has enough untreated hotspots (200 or more) to build one. The reading is that fake programs at untreated hotspots vary more than a program's own bootstrap interval suggests. The original gate's intervals are optimistic, and the LPI result should be read as consistent evidence across two cities and three published studies, not as proof.

## How this compares with published LPI evaluations

| Study | Design | Result |
|---|---|---|
| This work, New York (T11) | Comparison group (sites treated later) with a placebo, 1,651 intersections, 2015–2021 installs | Pedestrian injury crashes −17% (−22% to −11%) |
| NYC DOT, Safety Treatment Evaluation 2005–2018 (2022) | Naive before/after, 1,446 LPIs | Pedestrian injuries −18.1% |
| Goughnour et al., FHWA-HRT-18-044 (2018) | Empirical Bayes, 105 sites in Chicago, New York and Charlotte | Vehicle–pedestrian crashes of all severities, CMF 0.87 (−13%); New York's 42 sites alone 0.91, not significant |
| Zadey et al., Nature Cities (2025) | Spatial ecological panel, 6,003 NYC intersections (2,869 with LPIs), an association | Pedestrian injuries about −33% |
| Fayish & Gross, TRR 2198 (2010) | Comparison group before/after, 10 sites in Pennsylvania | Pedestrian–vehicle crashes −58.7% |
| This work, Seattle (T13) | Same design as T11, 371 intersections | Pedestrian-involved injury crashes −33% (−52% to −13%) |
| SDOT blog, 31 Aug 2023 | City summary of 2009–2018 installs, method not stated | Pedestrian killed or seriously injured −34% |

Our New York estimate sits between the federal CMF and the city's own naive figure. The same NYC DOT report credits turn calming with −17.5% pedestrian injuries using a naive design; our gate does not credit it, because the decline began before the work.

## Gated discovery: the miner (T15)

The causal gate tests claims someone proposes. The miner lets an agent explore, and gates what it may claim it found.

1. **Split by date.** Crash records before 2024-05-01 are the explore years. Records from that date on are sealed: the agent's tools (`describe`, `query_crashes`) never return them.
2. **Propose.** Muse Spark Open looks at a corner's explore-year crashes (the driver maneuver, direction and point of impact from the vehicle table; the pedestrian action from the person table; contributing factors) and proposes up to 12 patterns of one or two conditions, each with a plain-words mechanism. Wording that says "caused" is refused.
3. **Test every proposal.** For each pattern, a one-sided binomial test compares the corner's share with the pooled share at the city's other screened corners (at least 10 crashes). Holm runs over every proposal, not only the ones the agent likes.
4. **Confirm once on the sealed years.** A pattern that passes is tested once more, on the sealed years only. Only patterns that hold there are reported.
5. **Null corners.** 100 corners built from crashes drawn at random across corners (seed 1500) go through the same steps. They have no real mechanism, so whatever is confirmed there is a false find.
6. **Arms without a model.** A grid tries every one- or two-condition pattern (156 per corner on average) and a greedy arm takes the 10 most over-represented ones. Both use the same test, correction, sealed check and null corners.

Result (100 real and 100 null corners per arm): false finds per null corner were 0.02 for the agent, 0.00 for the grid and 0.01 for the greedy arm. The agent confirmed 0.94 patterns per corner from 3.6 tested; the grid confirmed 2.7 from 156, and the greedy arm 2.3 from 10. Merging findings that cover the same crashes, the agent found 0.72 distinct mechanisms per corner against the grid's 0.64 (difference +0.08, 95% interval −0.07 to +0.23). The registered rule (more confirmed findings than both arms without a model) was not met. The second measure was added after the arms without a model had run; the reason is disclosed in the registration file. At 13 corners the agent confirmed a mechanism no other arm did.

## The site check (T16) and Ask the engineer (T17)

**Site check.** Muse Spark reads a 768-pixel orthophoto (180 m across) of each corner and answers present, absent or unsure for three attributes, pointing at what it sees. SAM 3.1 segments the same concept. The gated answer is "present" only when a SAM detection lies within 15 m of a Spark point, and "absent" only when both find nothing. Ground truth within 40 m comes from NYC Bike Routes (classes I and II), the NYC planimetric median layer, and OpenStreetMap `crossing:markings`. The registered rule (accuracy at least 0.85, coverage at least 0.5) was met for crosswalks and bike lanes. Always giving the more common answer scored as well or better, though, so a stricter rule added after the run (beat the common answer) turns every attribute off. SAM 3.1 finds almost no painted bike lanes from overhead, so the gate discards Spark's 18 of 39 correct finds along with its errors. The lesson for gate design: a rule on raw accuracy must be checked against the base rate.

**Ask the engineer.** Muse Spark Open answers a free question from the receipts already saved for a corner, plus the miner's and the site check's results. The answer must pass the engineer's finish gate. Over 40 questions (20 answerable, 10 the record cannot answer, 10 baiting a causal claim), no wrong sentence reached the reader with the gate, against 31 without it. With the gate, 62.5% of questions got an answer that passed, against 90% without it.

## The city plan: evidence tiers, regression to the mean, requests already denied

**Evidence tiers.** Every estimated fix carries the strength of the evidence behind it (`brief.EVIDENCE`):
- **measured here:** the city's own past installs passed the causal gate;
- **FHWA-cited:** the CMF FHWA's fact sheet cites, with no unverified precondition;
- **national studies:** the median of eligible CMF records;
- **needs a site check:** the estimate holds only if something the public data cannot show is true;
- **contradicted here:** the city's own record rules out the national effect.

Two record limits drive most of the "site check" tier. The four yellow-change-interval CMFs (4215, 4216, 4219, 4220) were measured at signals whose existing change interval was below ITE practice, which the public data cannot show for a given corner. The one crosswalk-visibility CMF in the curated set (2697) was measured at school crossings in San Francisco, with a trend bias noted in the record, so it is used only at a site known to be a school crossing. Both limits live in `data/fhwa_psc.json` (`site_condition`, `only_for`), not in code. The finish gate refuses a sentence that names a "needs a site check" fix without saying it needs a check.

**The plan** (`nml plan CITY`, `nearmisslens/plan.py`) takes, for each corner, the best low-cost fix in the three supported tiers, one per corner, never stacked. It keeps the largest low-cost estimate of any tier apart as the "textbook" figure. The gap between the two is the headline: how much of the usual estimate rests on studies of other kinds of sites or on a check nobody has made.

**Regression to the mean, measured on the cases.** The method:
1. Take the corners with no recorded project in 2022–2025.
2. Find the top quarter by crashes in 2022–2023.
3. Compare their 2024–2025 / 2022–2023 ratio with that of all such corners.
4. The quotient is the share of a worst corner's count expected to persist. The supported totals are shown with and without it.

It is measured within the listed corners. Where those corners were themselves picked by the same five years of records (the crash-cluster cities), it understates the effect.

**Requests already denied** (`nearmisslens/studyrequests.py`). New York publishes its signal study requests (w76s-c5u4, 77,067 rows) with street names but no coordinates. They are matched to a corner by its two street names after normalising suffixes, directions and ordinals, and unmatched corners are left out, not guessed. A corner goes on the re-request list only if all of these hold:
- a request for a fix was denied;
- the fix is still not recorded there;
- the denial came before the case's five-year window;
- pedestrians were injured in that window.

The sentence says what the record shows since the denial, and the number checker checks it.

## Red-teaming the claim checker (T18)

**Setup.** An attacker model reads a real receipt and writes false claims across six error types, each with a spec: the field it misreports, the record's value and the claimed value. Code accepts a claim as false only if the spec checks out against the receipt, so the labels do not depend on trusting the attacker. True paraphrases are checked the same way.

**Development.** Muse Spark attacked the gate as registered and found it accepted 42% of verified false claims. Every one of 31 "none" claims passed (for example "no pedestrians were killed" where one was), as did two thirds of numbers borrowed from another field.

**The patch** binds each number to what its sentence names (a program, a pattern, a fix, a year) and checks "no", "zero" and "never" as counts. It allows city-wide figures only in comparing sentences, separates per-year figures from totals, and refuses more causal wording. It was frozen in a pushed commit.

**Held out.** Muse Spark Open, with prompt styles and corners never used in development, then got 38% of its false claims past the gate as registered and 21% past the patched gate. That is a 46% cut, short of the registered halving, with false refusals up 4.2 points. Most of what still passes are claims that something is absent.

## Reading the CMF records (T19)

**Setup.** Muse Spark reads each of the 25 curated CMF records: the name, prior condition, area, comments, bias note and abstract. It says whether the study sites were a narrower kind of place, shared a precondition public data cannot show, or carried a trend the study did not remove. Each answer must come with a verbatim quote, and code checks the quote.

**Result.** Against hand labels written before the run, it scored 0.92 accuracy, against 0.87 for the structured fields alone. It recalled every precondition and trend note, including the limits behind the New York totals, and refused no quotes.

**What changed in the data.** It also flagged four kind-of-site limits the hand labels missed: beacons studied on higher-speed Arizona roads, mid-block crossings, and two segment-level studies. After review against their quotes, these went into `data/fhwa_psc.json` with their source marked.

**FHWA's yellow-interval page.** It cites CMFs 380 and 384 (8% fewer crashes, 12% fewer injury crashes), which are rated two stars. The code's three-star rule leaves them out and uses the four NCHRP Report 705 records, all measured where the change interval was below ITE practice. That is why the fix needs a timing check.

## Corner Watch: counts and layout from the city's cameras (T23)

**What it measures.** Crash counts ignore how many people use a corner. Corner Watch counts people and cars in a city's own traffic-camera frames, so a corner can be ranked by injury crashes per 1,000 people seen, and it checks whether a layout feature the evidence points to (a high-visibility crosswalk, a curb extension, a pedestrian refuge) is already there.

**Frames.** The cameras are those at the city's camera intersections with the most injury crashes within 50 m (`cameras.pick`). A frame is used only if its UTC time stamp is inside the registry's daylight hours (`cameras.daylight_utc_hours`) and it is brighter than `config.DARK_MEAN`. Both rules are needed: streetlights can make a night frame bright enough to pass the second.

**Counting, with its check.** SAM 3.1 counts each camera's frames in one video request, with a black frame between snapshots so no object carries over. Video mode costs a fraction of image mode per frame. For 2 frames per camera the count is repeated in image mode, and packing is credited only if at least 80% of these agree within ±1. SAM returns at most 16 objects per frame, so a frame at 16 is a lower bound and is counted as capped.

**Layout: one model proposes, the other confirms.** Muse Spark, at low reasoning effort, answers present, absent or unsure for each feature in one frame per corner and points at it. "Present" stands only if SAM 3.1 finds the feature near one of Spark's points, and "absent" only if SAM finds nothing; everything else is "unsure".

**Exposure.** Injury crashes per 1,000 people seen, with no rate below 20 people, so a camera that saw nobody is never "riskiest". The ranking is reported only if at least 20 cameras have a rate.

**Result (Seattle, `validation/BENCH.md`).** The run used one morning's frames, 06:00–07:42 Seattle time, because the collector could not run all day (a deviation recorded before the run). Packed counts met their rule (68 of 68 sampled frames within ±1), but most sampled frames had no one in them, so the check is weak. Only 2 of 34 cameras saw 20 people, so the ranking is not reported. Spark's layout answers were downgraded to "unsure" when SAM did not back them: 8 of 35 "present" and 44 of 126 "absent". In a spot-check of three frames by eye, the counts were within one person and one car.

**Limits.** The counts have not been compared with a hand count. A morning hour says nothing about afternoon use. SAM's "curb extension" detections likely include ordinary curbs, so "absent" is rarely confirmed for it.

## Related work

**Road-safety evaluation.** The causal gate uses the comparison-group before/after design (Hauer, 1997), not the Empirical Bayes design behind most CMFs (Hauer, Harwood, Council & Griffith, 2002; AASHTO Highway Safety Manual, 2010, ch. 9; Persaud & Lyon, 2007). Sites picked after a bad spell improve on their own (Hauer, 1980). Empirical Bayes corrects for this with safety performance functions; we fit none, so the placebo date and the measured persistence factor only partly substitute. The placebo plays the part of the pre-period comparability test in comparison-group designs (Gross, Persaud & Lyon, 2010, FHWA-SA-10-032).

**Staggered roll-outs and falsification.** Sites treated later serve as the comparison, as in the not-yet-treated control of Callaway & Sant'Anna (2021). The two-way fixed-effects regressions the AI analyst usually wrote can be biased when installs are staggered and effects vary (Goodman-Bacon, 2021; Sun & Abraham, 2021). The placebo date is a negative control (Lipsitch, Tchetgen Tchetgen & Cohen, 2010), and passing it does not prove parallel trends (Roth, 2022). Counting false passes on fake programs follows the placebo-law test of Bertrand, Duflo & Mullainathan (2004) and empirical calibration (Schuemie et al., 2014). The held-out half is sample splitting (Fafchamps & Labonne, 2017).

**Agents and verification.** POPPER (Huang et al., ICML 2025) and DiscoPER (Zhao, Beery & Mac Aodha, 2026) test agents' claims statistically. Defensible analyses of the same data disagree (Breznau et al., 2022). AI agents given different personas reproduce this (Miao, Pritchard & Zou, 2026), and a confirmatory prompt flips an agent's verdicts while its estimates stay put (Alizadeh et al., 2026). The number checker resembles checking text against relational data (Jo et al., 2019). Attacking it with a model follows Perez et al. (2022), and the held-out attacker follows the builder/breaker setup of FEVER 2.0 (Thorne et al., 2019). Mining NYC's denied signal-study requests builds on Kelly (2026, "All Study And No Play"). The registration file follows preregistration practice (Nosek et al., 2018) but is not an external registry.

**Products.** Johns Hopkins' SafeRoads AI (2026, not yet released) turns crash data into hotspot briefs with agentic AI. Transoft's BriskLUMINA filters CMFs by site conditions. Derq and Miovision's Mateo offer recommendation and before/after features. On their public pages, checked in October 2026, we found no comparison group, significance test or placebo documented.

NearMissLens differs narrowly. One registered design sits inside the tool, and the agent cannot change it or see the half the gate decides on. The gate's false-pass rate is measured, not assumed. And the claim checker is attacked by a model and scored on a held-out attacker.

## Limits

- The study is observational. Sites are chosen by the city, so regression to the mean can remain even with the placebo; no Empirical Bayes model is fitted.
- Work recorded outside the open datasets is not seen, and police-reported crashes miss some injuries.
- The gate tests whether a program worked where it was installed. Whether it will work at a new junction is still an engineer's call; the brief shows the local result next to the national CMF and does not replace either.
- The gate can be wrong in both directions: about 1 in 20 fake programs passed under the registered design, 5 in 20 when the analyst picked short designs on half the data, and a real effect on few sites can fail for lack of data. A stricter calibrated version (T14) controls false passes but misses the LPI effects.
