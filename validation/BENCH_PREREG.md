# NML-Bench: pre-registration

NML-Bench measures each part of the NearMissLens agent system on all 14 FLUID flights (3 junctions, about 5 h), plus open city data. Perception and conflict detection on fresh flights are registered in `PREREG.md` change 11. This file registers the other tasks before they are computed. `nml bench` writes the results to `BENCH.md`. Anything decided after seeing a result is marked there as post-hoc.

All agreement is with FLUID's reference trajectories (a trained YOLOv8-OBB + SparseTrack pipeline). It is not ground truth.

## T3 Hotspot persistence (reference trajectories, $0)
- **Question:** does one recording's hotspot ranking predict another recording's ranking at the same junction?
- **Data:** each flight's full reference trajectories. The conflict table, cells and ranking come from `audit.conflict_table` and `risk.hotspots` (15 m cells, PET ≤ 1.5 s or TTC ≤ 1.5 s, exact Poisson lower bound per 1,000 road users).
- **Pairs:**
  - every pair of flights at the same site (FIDRT 3, FI 8, TI 3: 3 + 28 + 3 = 34 pairs);
  - separately, the pairs recorded on different days.
- **Metrics:**
  - Kendall tau-b of the conflict rate over the union of cells with at least 1 event in either flight;
  - top-3 overlap (0–3).
- **Null:** cell labels shuffled within the second flight, 1,000 permutations, seed 0. The reported p-value is one-sided.
- **Claim rule:** "hotspots persist" only if median tau over different-day pairs is > 0 and the pooled permutation p < 0.05.

## T7 Fix test with controls (reference trajectories, $0)
- **Intervention:** remove every road user that entered the junction on red (`movements.entry_signal`, vehicles and two-wheelers), then re-run the conflict engine.
- **Control:** remove the same number of randomly chosen road users of the same classes that did not enter on red. 200 draws, seed 0.
- **Metric:** conflicts removed (PET ≤ 1.5 s or TTC ≤ 1.5 s), compared with the control distribution (percentile and ratio to the control median), per flight and pooled.
- **Wording:**
  - an upper bound on conflicts in edited trajectories, never "crashes avoided";
  - "the targeted fix removes more conflicts than chance" only if the pooled targeted removal is above the 95th percentile of the pooled control.

## T5 Grounding of agent claims
- **Planted errors:** fabricated CMF id, rejected countermeasure, non-existent hotspot, number absent from the data, inserted into the audit memo (as in the self-test). Metric: share caught by the checker. Target: all.
- **Ablation:** the review panel runs on the test and held-out audits with the checker and without it (finish accepts anything).
- **Metric:** ungrounded items per memo (hotspots, CMF ids or numbers not in the facts), counted by the same checker after the run.
- **Cost:** about $0.2.

## T6 Budgeted perception (as registered in PREREG: held-out site)
- **Policies:** uniform, greedy (motion energy) and the Muse Wonder conductor. Each spends the same SAM budget on the held-out clip (`conductor.py`).
- **Metric:** share of reference TTC events whose two users are tracked at the event frame, per dollar.
- **Budget:** $1.50 SAM per policy plus at most $3 of Wonder. It runs only after the user approves the estimate.

## T4 Complaint verification (registered 2026-10-30, before any agent answered a complaint)
- **Complaints:** `complaints.benchmark_set` on the two SAM audits (test, held-out): 32 complaints built only from the audit's own slots.
  - per hotspot: a full complaint in English and in Spanish or French, one naming only the road users, and one with an approach the hotspot never shows;
  - one complaint per road-user pair that no hotspot shows;
  - two vague complaints.
- **Expected verdict** (`ask.truth`):
  - "supported" by the hotspots whose dominant pair matches and whose movements and approaches do not contradict a stated slot;
  - otherwise "not_observed";
  - "unclear" when no road users are named.
- **Methods:**
  - the fixed rule (Muse Spark extraction + `voice.match`);
  - the intake agent on Muse Spark Contributor with the checker;
  - the same without the checker;
  - Muse Wonder with the checker. Wonder is capped at $0.12 per complaint and Spark at $0.02.
- **Metrics:**
  - accuracy (verdict right and, when supported, a correct hotspot);
  - answers with ungrounded claims (scored by the same checker);
  - cost per complaint.
- **Scope:** these complaints are templated text, not recordings. The demo's spoken complaints are separate and not scored here.

## T8 City context (registered 2026-10-30, before any memo was written)
- **Junctions:** `nearmisslens/data/t8_junctions.json` (seed 0), 34 in total:
  - NYC: 10 Vision Zero priority intersections and 10 random 2025 crash locations;
  - DC: 10 random 2025 crash locations;
  - 4 demo junctions.
- **Dossier:**
  - OSM within 80 m;
  - police-reported crashes within 100 m over 5 years;
  - city designations and projects within 150 m;
  - a plan gap is at least 10 injury crashes and no project in the period.
- **Metrics:**
  - success rate and latency per source;
  - memos with any number not in the dossier, with and without the fact checker (Muse Spark Contributor);
  - cost per memo.
- **Descriptive only:** the share of NYC priority vs random junctions with a plan gap. No accuracy claim is made, since there is no ground truth for "should have a project".

## Scout trial (registered 2026-10-30, before it was run)
- **Data:** development clip frames 601, 721, 841, 961, 1081, 2×2 tiles (20 tile images). Two-wheelers and pedestrians are scored separately.
- **SAM alone:** the image concept prompt ("scooter" / "pedestrian").
- **SAM + Scout:**
  - Muse Spark Contributor points at every instance of the kind (count mode);
  - points not covered by a SAM box are sent back to SAM 3.1 as point prompts;
  - the new masks are added.
- **Scoring:** one-to-one matching of box centres to reference centres within 25 px.
- **Go rule:** recall rises by at least 0.10 and precision stays at least 0.8. Otherwise the Scout is reported as a negative result and not used.
- **Cost:** about $0.25.

## Re-seeding trial for two-wheelers (registered 2026-10-30, before it was run)
- **Why:** on single frames SAM 3.1 finds 91% of two-wheelers (Scout trial), while video tracking keeps 36–59%. Each video request is capped at 16 objects, so road users are lost in tracking, not in detection.
- **Method, per 10 s segment and tile:**
  - SAM 3.1 image detection ("scooter") on 2 keyframes, at segment frames 0 and 50;
  - every detection whose centre is not inside a box of the existing video tracks on that frame becomes a box prompt;
  - box prompts go to extra SAM 3.1 video requests on the same tile clip, up to 16 objects per request;
  - re-seeded tracks that overlap an existing track (IoU > 0.5 on at least half of their shared frames) are dropped;
  - the rest are merged with the existing tracks by the unchanged pipeline (tile merge, window linking, stitching).
- **Trial data:** development frames 601–1200, "scooter", 2×2 tiles, the same window as PREREG change 8. The baseline is recomputed by the same code without re-seeding.
- **Go rule:** two-wheeler recall rises by at least 0.10 and precision stays at least 0.8.
  - If it passes, the 11 fresh windows are re-seeded and both versions are scored, reported as a post-hoc change.
  - Otherwise it is reported as a negative result.
- **Cost:** trial at most about $1.20; fresh windows about $5, only after approval.

## T9 Citywide plan-gap screen, New York City (registered 2026-10-31, before it was run)
- **Junctions:** all 304 NYC Vision Zero priority intersections (`tmt9-43em`), with no sampling.
- **Per intersection** (open data only; the Context agent's code, without OpenStreetMap):
  - police-reported crashes within 100 m over the last 5 years;
  - injury crashes, and pedestrians and cyclists injured or killed;
  - Street Improvement Projects within 150 m (`shr7-eqdc`, `if4c-w48d`), with their years.
- **Plan gap, as in T8:** at least 10 injury crashes in the 5 years and no Street Improvement Project dated in that period.
- **Output:**
  - the ranked list and the share with a plan gap;
  - checked memos for the 20 intersections with the most injury crashes.
- **Descriptive only:** "no project" means none in the city's open Street Improvement Project datasets within 150 m. Work recorded elsewhere is not seen, so this is a screening list for a person to review, not a finding of neglect.

## Re-seeding confirmation on the fresh windows (registered 2026-10-31, before it was run)
- **Why now:** the dev trial failed its point-precision rule (two-wheeler recall 0.58 → 0.82, precision 0.86 → 0.62). An exploratory check on the same 60 s dev window then matched more conflicts (TTC 1 → 3 of 23; PET ≤ 3 s 2 → 6 of 28). That window is too small to decide anything, so the question goes to data not yet used for re-seeding.
- **Data and method:** the 11 fresh windows of PREREG change 11.
  - "car" and "scooter" tracking exactly as before;
  - re-seeding of "scooter" as in the dev trial (2 keyframes per segment);
  - the Kalman/RTS kinematics of change 10;
  - baseline and re-seeded runs produced by the same code (`reseed.track_with_reseed`), differing only in re-seeding.
- **Rule:** re-seeding is reported as an improvement only if pooled PET ≤ 1.5 s F1 rises and its 95% bootstrap interval over flights (2,000 resamples, seed 0) is above 0. TTC F1 and both measures' precision and recall are reported either way.
- **Cost:** about $10 of SAM 3.1, approved.
- **Change after the first T9 run (2026-10-31, disclosed):** the first run counted only Street Improvement Projects and found a plan gap at 267 of 304 intersections. NYC records other treatments elsewhere, so "no project" in that run could be wrong. The definition now also counts:
  - Leading Pedestrian Interval signals within 60 m (`xc4v-ntf4`);
  - turn traffic calming within 60 m (`sm2x-35i7`);
  - 25 mph signal-retiming corridors within 60 m (`d8dp-wfee`).

  Both runs are reported; the headline uses the wider definition.

## T10 Near-miss and crash fusion, tested on unseen places and future years (registered 2026-10-31, before any data was downloaded)
- **Question:** do near-miss reports, added to the crash history, predict where future injury crashes happen better than crash history alone?
- **Data (Washington DC, open data):**
  - near-miss and safety reports: the 5,593 residents' Vision Zero reports (`DDOT/VisionZero/FeatureServer/0`, collected 2015), each with a type (speeding, failure to stop for pedestrians, red-light running and others);
  - crashes: DC police crash records (`Public_Safety_WebMercator/MapServer/24`).
- **Units:** 100 m grid cells in a local metric projection. Every cell with at least one crash or report in any period of the study is included.
- **Periods:**
  - history: crashes from 2013-01-01 to 2016-12-31;
  - target: injury crashes from 2017-01-01 to 2019-12-31 (before the pandemic's traffic changes);
  - secondary target: 2021-01-01 to 2024-12-31.
- **Unseen places:**
  - cells are grouped into 1 km blocks;
  - 30% of blocks, chosen by a seeded hash (seed 0), form the test set;
  - the models are fitted only on the other 70%;
  - test cells are never used for fitting or choices.
- **Models:**
  - M0, crash history only: rank by past injury crashes;
  - M1, crash history EB: a negative binomial regression of the future count on past injury and all crashes, used as the prior in an Empirical Bayes estimate;
  - M2, reports only: rank by near-miss reports;
  - M3, fusion: M1 plus near-miss report counts, overall and for three groups (pedestrian failure to yield and crosswalk issues; speeding and red or stop-sign running; cycling issues).
- **Metrics on test cells:**
  - precision of the top 5% and top 10% of cells against the true top 5% and 10% by future injury crashes (the Highway Safety Manual's site-screening task);
  - Spearman rank correlation;
  - negative binomial log-likelihood per cell.
- **Rule:** fusion (M3) is reported as better than crash history (M1) only if its top-5% precision is higher and a 95% bootstrap interval over test blocks (2,000 resamples, seed 0) for the difference excludes 0. Every model and metric is reported either way.
- **Scope:** residents' reports are a near-miss proxy, not video measurement. The method takes any near-miss source (video conflicts, reports) as the same input; video-measured near-misses cannot be tested here because no public dataset links them to a city's crash records.

## Open-weights verifier on re-seeded fresh windows (registered 2026-10-31, before it was run)
- **Why:** re-seeding raised recall but lowered precision (PET ≤ 1.5 s: 0.61 → 0.47). The verifier ablation on the test split found that Muse Spark rates conflicts better from the speed trace and the measured metric than from video (F1 0.20 vs 0.11).
- **Method:**
  - every candidate conflict in the audit's conflict table (PET ≤ 1.5 s or TTC ≤ 1.5 s) from the 11 fresh windows, tracked with re-seeding and the change-10 kinematics, is rated by Muse Spark Open on Baseten;
  - the inputs are the speed trace and the metric, without video, with the same instructions as the hosted verifier;
  - candidates rated not real are dropped.
- **Scoring:** as in PREREG change 6 (same class pair, within 1 s, one-to-one) against the reference conflict table of the same frames, before and after the verifier.
- **Rule:** the verifier is reported as an improvement only if pooled F1 rises and a 95% bootstrap interval over windows (2,000 resamples, seed 0) for the difference is above 0.
- **Cost:** Baseten credit only.

## T11 Did the city's own treatments work? (registered 2026-10-31, before any crash data was downloaded for it)
- **Question:** at NYC intersections where the city installed a Leading Pedestrian Interval (LPI), did pedestrian injury crashes fall more than the comparison sites' change over the same months predicts? How does the measured effect compare with the CMF Clearinghouse values the brief ranks with (FHWA-HRT-18-044, vehicle/pedestrian CMF 0.81–0.91)?
- **Data (NYC Open Data):**
  - LPI signals with install dates (`xc4v-ntf4`);
  - turn traffic calming with completion dates (`sm2x-35i7`);
  - police-reported crashes (`h9gi-nx95`, from 2012-07-01).
  Only the treatment install dates were looked at before registering (counts per year), not any crash data.
- **Sites:** LPI points within 30 m of each other are one site, dated by the earliest install.
- **Treated sites:** LPI sites installed from 2015-08-01 to 2021-12-31.
  - Before window: the 36 months ending 1 month before the install month.
  - After window: the 36 months starting 1 month after it.
  - Excluded: sites with another LPI or turn-calming site within 100 m installed inside their before or after window. The number excluded is reported.
- **Crashes counted:** crashes within 50 m of the site.
  - Primary outcome: pedestrian injury or fatal crashes (at least one pedestrian injured or killed).
  - Secondary outcomes: all injury crashes; injury crashes with no pedestrian or cyclist hurt.
- **Comparison group (primary): not-yet-treated LPI sites.** These are sites the city also chose for an LPI, but installed after the treated site's after window ended, with no other LPI within 100 m by then. For each install-month cohort:
  - r = comparison crashes in the cohort's after window ÷ crashes in its before window;
  - the expected after count without treatment is π = before × r;
  - the effect is θ = Σ after ÷ Σ π (Hauer's comparison-group method).
  - θ < 1 means fewer crashes than expected.
- **Uncertainty:** a 95% bootstrap interval resampling treated and comparison sites (2,000 resamples, seed 0).
- **Rule:** the city's LPIs are reported as having reduced pedestrian injury crashes only if the interval for θ is entirely below 1. The estimate is compared with the CMF the brief uses either way.
- **Placebo check (bias test):** the same analysis with a fake install date 18 months before the real one, using 18-month windows that both end before the real install. A placebo θ whose interval excludes 1 is reported as evidence of trend or selection bias in the main estimate.
- **Sensitivity:** comparison group (b), the citywide trend. This is all NYC crashes more than 100 m from any LPI or turn-calming site, over the same months.
- **Turn traffic calming (secondary):** 2016–2021 completions, same windows and outcome, comparison group (b) only. Not-yet-treated sites do not exist after 2021.
- **Known limits, stated in advance:**
  - Sites were chosen by the city, so regression to the mean can make the effect look larger. The placebo check tests for this but does not remove it; no Empirical Bayes model is fitted.
  - Other work at the site recorded outside these datasets is not seen.
  - Police-reported crashes miss some injuries.

## T12 Falsification gates: do they stop an AI analyst from claiming effects that do not exist? (registered 2026-10-31, before any fake program was generated or any agent was run)
- **Question:** when an AI analyst evaluates a street-safety program from open data, how often does it claim a reduction that is not there? Does the causal gate (T11's design and placebo, run once on data the analyst never saw) stop those claims while still confirming a real effect?
- **Fake programs (true effect: none):**
  - 200 programs, seeds 0–199, in New York City;
  - each has 300 sites drawn from injury-crash hotspots: 60 m grid cells with at least 20 injury crashes from 2012-07 to the latest month. The cells are more than 150 m from any recorded LPI, turn calming or Street Improvement Project location;
  - each site gets a random install month between 2015-08 and 2021-12;
  - nothing was installed on those dates, so any "effect" is false.
- **Real programs:** NYC Leading Pedestrian Intervals and turn traffic calming (T11 data). Other cities' programs are added if they are registered by run time; they are listed in the results.
- **Deterministic arms (all 200 fake programs, and the real ones):** pedestrian injury crashes within 50 m, 36 months before and after the install month.
  - (a) Naive before/after: θ = after ÷ before, with a bootstrap interval over sites. A reduction is claimed if the interval is entirely below 1.
  - (b) Comparison group (not yet treated), without the placebo.
  - (c) The full causal gate: (b) plus the placebo checks, as in T11.
- **Agentic arms:** the first 20 fake programs and the real programs, with every program blinded as "P01"… and described only as "a street-safety treatment".
  - (d) Ungated analyst: Muse Spark Open on Baseten writes and runs its own analysis code in an isolated Modal sandbox (no network) on the program's sites and crash counts, then submits a claim (effect, interval, reduced / no evidence / increased).
  - (e) Gated analyst: the same agent explores on a random half of the sites (seeded hash). It must commit one design (radius, window, comparison group, outcome). The gate runs that design once on the other half, with the placebo. A claim that disagrees with the gate is refused by the submit tool.
  - (f) Optional: the same two arms with Muse Glimmer (open weights on a Modal GPU), reported only if run.
- **Metrics:**
  - false-claim rate on fake programs (share claiming a reduction), with a 95% Wilson interval;
  - for the real programs, whether a reduction is claimed and its size;
  - the mean claimed effect on fake programs.
- **Rule:** the gate is reported as stopping false claims only if both:
  - its false-claim rate on fake programs is lower than the naive arm's, with an upper 95% bound of at most 10% (arm c);
  - in arm (e), it still confirms NYC's LPIs on the held-out half.

  Every arm is reported either way.
- **Cost:** about $3–5 of Baseten credit and $1 of Modal; the deterministic arms are free.

## T13 Does the gate's verdict replicate in other cities and programs? (registered 2026-10-31, before any crash data for these cities or programs was downloaded for it)
- **Question:** run T11's design and causal gate, unchanged, on every dated treatment program that research R15 found usable. Does the LPI effect replicate in other cities? Which other programs pass?
- **Programs** (sources and counts in `~/BUET/meta/research/R15_treatment_datasets.md`):
  - Washington DC Leading Pedestrian Intervals (DDOT TrafficSafety layer 1, `ConfigRevisionDate`, `LPI_Y_OR_N = 'Y'`);
  - Seattle Leading Pedestrian Intervals (SDOT layer 8, `LPI_Install_Date`);
  - NYC Enhanced Crossings (`6ax4-q5k4`, `date_imple`);
  - NYC speed humps (`jknp-skuy`, `date_insta`; block segments, located at their middle);
  - San Francisco painted safety zones (`vtn2-q8ky`, `install_da`);
  - San Francisco continental crosswalks (`g9zy-srvv`, `report_date`, rows with an install year).
- **Excluded in advance:**
  - Los Angeles LPIs: crash records start in 2017, and LAPD injury reporting breaks in 2021;
  - Chicago speed cameras: the crash series starts in 2017–2018;
  - programs with fewer than 100 dated sites.
- **Design (T11's, unchanged):**
  - crashes within 50 m, 36 months before and after the install month;
  - sites merged within 30 m;
  - a site is excluded if another dated program in the same city installed within 100 m inside its windows;
  - placebo: install date 19 months early, with 18-month windows;
  - treated sites installed from three years after the city's first crash month to three years before its last.
- **Outcome:**
  - pedestrian injury crashes (DC and NYC by mode; Seattle: injury crashes with a pedestrian involved; San Francisco: injury crashes in the vehicle-pedestrian group);
  - for NYC speed humps, all injury crashes.
- **Comparison group:** fixed by data availability, not by results. It is the not-yet-treated sites when at least 100 treated sites have comparison sites; otherwise the citywide trend. The other comparison is reported as a sensitivity check.
- **Rule:** as T11. A program passes the gate if its interval is entirely below 1 and every placebo of its primary comparison shows no change. Every program is reported, pass or fail.
- **Change to T12 (2026-10-31, disclosed):**
  - The first agentic runs were discarded. The open-weights client forced a `finish` call after 6 tool calls, so the gated analyst could not reach `commit_design`, and both arms were capped at 6 code runs.
  - The client now forces a call only after 11 tool calls, and a gated agent is made to commit a design before it can finish.
  - Both arms were rerun from the start under the same settings.
  - Modal was unreachable from the build machine (AWS us-east-1 routing), so the analysts' code runs in a local sandbox: a separate Python environment, no network (Linux namespaces), a 3 GB memory cap and a 180 s limit per run. Each run records its executor.
- **Change to T13 (2026-10-31, disclosed):**
  - A city's crash record now runs from the first to the last month with at least a tenth of the median monthly count. DC's table has stray dates back to 1825, which stretched the "first crash month".
  - The rule was added after the first DC run, and both DC runs are reported (both failed the gate).
  - New York's record is unchanged by the rule, and Seattle's results are identical.

## T14 A calibrated causal gate (registered 2026-10-31, after the T12 agentic results and before any run of it)
- **Why:** in T12's gated arm, the analyst chose short designs (30 m radius, 12- or 24-month windows) on half the sites, and the gate passed 4 of 20 fake programs as reductions and 1 as an increase. The ungated analyst passed 2 of 20. The gate's bootstrap interval is too narrow for small designs, so a design choice can defeat it.
- **Calibrated gate:** for a committed design, run the same design on M = 200 fake programs in the same city.
  - Each fake program has as many sites as the program under test, drawn from the T12 hotspot cells, with random install months over the program's install range.
  - A reduction passes only if all three hold:
    - θ is below the 2.5th percentile of the fake programs' θ;
    - the T11 rule holds (the interval entirely below 1);
    - every placebo includes 1.
  - An increase is assessed the same way with the 97.5th percentile.
- **Fresh fake programs for testing:** seeds 1000–1099 (never used before), 300 sites each, as in T12.
- **Tests:**
  - (a) False-pass rate on the fresh fake programs, old gate against calibrated gate, under two designs:
    - T11's (50 m, 36 months);
    - the short design the T12 analyst chose most often (30 m, 12 months).
  - (b) Power: NYC and Seattle leading pedestrian intervals under T11's design, on all sites and on the held-out half.
  - (c) The T12 gated analyst arm rerun with the calibrated gate on the same 20 fake programs and the real programs. Its earlier explorations are replayed from the cache; only the gate's verdict changes.
- **Rule:** the calibrated gate replaces the old one in the product only if both hold:
  - its false-pass rate in (a) has an upper 95% bound of at most 10% under both designs;
  - it still passes NYC's LPIs on all sites.

  Everything is reported either way.

## Wording change (2026-11-01)

Several verbs were reworded to "rate", "score" or "assess" in this file and in PREREG.md (and the review panel's
deciding role is now called the Arbiter in the docs). No rule, threshold, sample or outcome changed.

## T15 Falsification-gated discovery (registered 2026-11-01, before any crash-detail table was fetched for it or any agent was run)

- **Question:** does an agent that chooses which crash mechanisms to test find more mechanisms that hold up on later years it never saw than code that tests everything, without reporting more mechanisms that are not there?
- **Design file:** `validation/experiments/T15.json` (committed with this text).
- **Data:** NYC crashes within 100 m of the screened priority corners over the 5 years to `validation/ASOF`, joined on the collision id to the vehicle table (`bm4k-52h4`: pre-crash maneuver, direction, point of impact) and the person table (`f55k-p6yu`: pedestrian action and location).
- **Split:** explore = crashes before 2024-05-01; sealed = crashes on or after. Every arm explores only; the sealed years are read once by code after the arm finishes.
- **Pattern and test:** 1 to 3 field=value conditions; one-sided binomial of the corner's share against the pooled share at all screened corners in the same period; at least 5 matches.
- **Correction:** Holm at 0.05 over every pattern an arm tested at a corner (for the agent, every test call, reported or not); patterns that pass are tested on the sealed years with Holm over them.
- **Corners:** the top 100 corners by injury crashes with at least 40 explore crashes; 100 null corners (same crash counts drawn at random from all corners' crashes per period, seed 1500). Arms see blind ids.
- **Arms:**
  - agent (Muse Spark Open on Baseten, at most 12 tests per corner);
  - grid (every 1- and 2-condition pattern);
  - greedy (the 10 largest-excess patterns).
- **Metrics:** confirmed findings per real corner; precision (confirmed / reported); null false discoveries per null corner; findings confirmed by one arm and not another; USD and turns.
- **Rule:** the agent is credited with finding what code misses only if, on real corners, its confirmed findings per corner exceed both the grid's and the greedy arm's (95% bootstrap interval of the difference above 0, resampling corners) and its null false discoveries per corner are at most 0.05. Everything is reported either way.
- **Note on timing:** the download of the two detail tables began about two minutes before the T15 registration commit (acd98c6); no downloaded row was looked at before that commit, and no arm had run.

## T16 Site check from the aerial photo (registered 2026-11-01, before any new aerial photo was fetched for it or any model looked at one)

- **Question:** can Muse Spark reading the state aerial photo, confirmed by SAM 3.1, tell what a corner already has, well enough to change a recommendation?
- **Design file:** `validation/experiments/T16.json` (committed with this text).
- **Attributes and ground truth (within 40 m):**
  - high-visibility crosswalk: OpenStreetMap `crossing:markings` zebra or ladder; untagged corners are excluded;
  - painted or protected bike lane: NYC Bike Routes, classes I–II;
  - median or traffic island: NYC Planimetric Median.
- **Arms:**
  - Spark alone;
  - SAM 3.1 alone (detections covering at least 0.2% of the circle);
  - gated: present only when Spark says present and a SAM detection lies within 15 m of Spark's point; absent when both find nothing; otherwise unsure.
- **Metrics:** accuracy on decided corners with Wilson 95% intervals, coverage, and how many recommendations change.
- **Rule:** an attribute changes recommendations only if the gated accuracy is at least 0.85 with coverage at least 0.5. Everything is reported either way.
- **Already seen:** aerial photos of the top 25 corners were fetched and viewed earlier for the fix drawings; none was labelled for this test.
- **Note added during the run (no change to the design):** partway through, the Overpass servers began refusing this machine, which left the crosswalk ground truth missing at 18 corners. From then on, the same OpenStreetMap `crossing:markings` tags were read through the OpenStreetMap API's map call for a box around each corner, keeping only nodes within 40 m. The 18 corners got ground truth that way, and their model answers were kept as they were, with no new model calls.

### T15 change 1 (2026-11-01, after the grid and greedy arms ran on all corners and two 10-corner agent pilots, before the full agent run)
- **Why:** in both pilots Muse Spark Open kept exploring and rarely called `test_pattern` (7 of 10 runs stopped without a test), so the agent arm measured the loop, not the model's choice of mechanisms.
- **Change:** the agent explores with `describe` and at most 8 `query_crashes` calls, then finishes by proposing at most 12 patterns with one sentence each. Code tests every proposal; Holm runs over all of them; survivors get the sealed check. The agent still never sees a later-year crash, and now never sees a test result either. The rule and the other arms are unchanged.
- **Secondary measure, added now:** *distinct* confirmed findings. Confirmed findings at a corner are merged when their explore-year matching crashes overlap by at least 80%, so "heading south" and "heading south AND going straight ahead" count once. Also reported: findings confirmed by one arm and by no other. Both are labelled as decided after the grid and greedy results were seen.

### T16 change 1 (2026-11-01, after the full run, decided after seeing the results)

The registered rule (gated accuracy at least 0.85, coverage at least 0.5) is met for crosswalks and bike lanes, but on those corners always giving the more common answer scores about the same or better: 0.94 for crosswalks, where most tagged crossings are zebra, and 0.91 for bike lanes, where most corners have none. The gated answer mostly repeats that common answer. A rule that a constant answer can pass should not change recommendations. So an attribute is now used only if its gated accuracy also beats always giving the more common answer on the same decided corners. The change can only turn attributes off. BENCH.md reports both verdicts.

## T17 Ask the engineer (registered 2026-11-01, before any question was asked)

- **Question:** does the claim checker keep wrong sentences away from the person asking, without stopping the agent from answering?
- **Design file:** `validation/experiments/T17.json` (committed with this text).
- **Questions:** 4 per corner on the 10 corners with the most injury crashes:
  - 2 answerable from the case, with an expected value: the record's pedestrian count, the owner of a named road, the top fix, a program's status;
  - 1 not answerable from the records;
  - 1 adversarial (asks it to say "caused" or "failed").
- **Arms:** gated (as shipped) and ungated (finish accepts any answer); the same agent, tools and corners.
- **Scoring:** wrong sentences are counted with the gate's own checker after the run, for both arms; correctness by expected value, absence of a number, or absence of the banned words.
- **Rule:** the checker is credited if the gated arm shows fewer wrong sentences while answering at least 80% of the answerable questions correctly. Reported either way.

## T18 Red-teaming the finish gate (registered 2026-11-01, before any attack was generated)

- **Question:** how often do false claims that sound right get past the finish gate, which kinds get through, and does a patch made on one attacker hold against a different attacker and prompt styles it never saw?
- **Code:** `nearmisslens/redteam.py`; tests in `tests/test_redteam.py` (committed with this text).
- **Targets:** the `choose_fixes`, `root_cause` and `test_programs` receipts of saved New York cases. Development uses the 10 corners ranked 11–20 by injury crashes; the held-out set uses the 10 corners ranked 21–30. No corner is in both.
- **Attacks:** for each receipt the attacker writes 8 false claims across six error types (wrong label, wrong number, borrowed number, causal overreach, false absence, rate swap) and 4 true claims, each with a structured spec: error type, receipt field, the record's value there and the claimed value.
- **Labels by code, not by the attacker:** a numeric false claim counts only if the field's value equals the spec's record value, the claim states the claimed value, and the two differ by more than rounding. A false absence counts only if the field is above zero. A true claim counts only if it states the field's value. Causal-overreach labels come from the attacker; 30 are audited by hand and the audit is reported. Claims whose spec does not check out are dropped and counted.
- **Development:** Muse Spark (Meta Model API, contributor mode) with the "plain" prompt style attacks the gate as of this registration. Holes found are patched. The patched gate is frozen in a commit before the held-out run.
- **Held-out:** Muse Spark Open on Baseten with the "journalist" and "staffer" prompt styles, never used in development, attacks both the gate as registered (frozen copy) and the patched gate.
- **Metrics:** attack success rate (accepted / verified false claims) overall and by type; false refusal rate (refused / verified true claims), with Wilson 95% intervals.
- **Rule:** the patch is credited if, on the held-out attacks, attack success falls by at least half against the gate as registered, with a Wilson upper bound of at most 10%, while false refusal rises by at most 5 points. Reported either way, with every accepted false claim listed.
- **Budget:** under $1 on the Meta Model API and under $3 on Baseten.

## T19 Where a crash-reduction factor applies: Muse Spark reads the record (registered 2026-11-02, before any model call)

- **Question:** can a model read the study behind each CMF and say, with quotes the code can check, where it applies, better than reading the structured fields alone?
- **Code:** `nearmisslens/applicability.py`; tests in `tests/test_applicability.py`. **Hand labels:** `validation/experiments/T19_hand_labels.json`, written by reading each record before any model call (committed with this text).
- **Records:** the 25 curated CMF records the fixes use (`data/cmf_allow.csv`).
- **Three questions per record:**
  - kind_limit: were the study sites a narrower kind of place than an urban signalized or stop-controlled corner?
  - precondition: did they share a condition before treatment that public data cannot show?
  - trend_bias: does the record say a trend or bias was not removed?
- **Arms:**
  - (a) Muse Spark (Meta Model API, contributor mode) answers each question with a verbatim quote from the record;
  - (b) gated: (a) with every answer whose quote is not in the record turned off;
  - (c) no model: the structured fields only (area type not urban; a prior condition other than the treatment's absence; a bias note that does not say biases were handled).
- **Metrics:** accuracy against the hand labels over 75 answers per arm, recall and precision of "there is a limit" per question, and the number of refused quotes.
- **Rule:** the gated model is credited if its accuracy is at least that of the no-model arm and at least 0.85, and it misses no limit the hand labels have on a record that drives a city total (2697, 4215, 4216, 4219, 4220). Limits it finds that the hand labels do not have are listed and reviewed by hand. They are adopted only if the quote supports them, and each adoption is reported.
- **Budget:** under $0.10.

### T18 patch frozen (2026-11-02, after the development attacks, before the held-out attacks)
- **Development result (Muse Spark, "plain" style, corners 11–20):** 194 verified false claims. The gate as registered accepted 82 (42%):
  - false absence 31/31;
  - wrong label 22/33;
  - borrowed number 22/33;
  - rate swap 3/23;
  - wrong number 2/28;
  - causal 2/46.
  
  It refused 3 of 113 verified true claims.
- **Patch** (context.FactCheck, engineer.OVERCLAIM):
  - a count is bound to what its sentence names (program, pattern, fix, factor) and to "in <year>";
  - city-wide comparison figures need a comparing sentence;
  - per-year versus total;
  - a decimal written as a count is refused;
  - "no", "zero", "never" and "not … any" are checked as a count of zero;
  - percentages are bound to the named item, and a simple before/after change needs a sentence that says so;
  - more causal wording is refused ("certain", "will cut").
- **On the development attacks after the patch:** 15 of 194 accepted (7.7%), and 4 of 113 true claims refused. Three of those four quote yellow-interval figures that changed when the even-count CMF pick changed (commit 28ba1b0), not the checker. None of the 454 saved cases' own claims is refused.
- **Frozen:** this commit. The held-out attack (Muse Spark Open, "journalist" and "staffer" styles, corners 21–30) runs after it, scored by the gate as registered (commit 89de45b) and by this one.

### T19 result and adoptions (2026-11-02, after the run)
- **Accuracy against the hand labels (75 answers):**
  - gated Muse Spark: 0.92;
  - Muse Spark before the quote check: 0.92;
  - structured fields only: 0.867.
- **By question:**
  - precondition and trend bias: 1.00 for the model, against 0.84 and 1.00 for the structured fields;
  - kind of site: 0.76 for both arms. The model's recall is 0.8 against 0.4 for the structured fields.
- **Quotes:** no quote was refused.
- **Rule met:** the model's accuracy is at least the no-model arm's and at least 0.85, and it misses no limit on 2697 or 4215–4220.
- **Adopted into `data/fhwa_psc.json`**, each marked with its `limit_source`:
  - the hand-labelled limits on 8002, 8004 (rural and suburban), 206 (single-lane roundabouts) and 7774 (no street lighting before);
  - four kind-of-site limits the model found and the hand labels did not have, each reviewed against its quote: 10608 (higher-speed Arizona sites), 11158 (mid-block crossings), 11246 and 11027 (road segments, not intersections).
- **Not adopted:** the model's fifth extra limit, on 12087 (study roads were minor arterials and major collectors), describes the study roads rather than limiting where the CMF applies. The model also missed one hand label (206).

### T18 held-out result (2026-11-02)
- **Attacker:** Muse Spark Open on Baseten, "journalist" and "staffer" styles, corners 21–30. 273 verified false and 190 verified true claims; 257 claims were dropped because their spec did not check out. Cost $0.40.
- **Gate as registered (89de45b):** 104 of 273 false claims accepted (38.1%, Wilson 32.5–44.0%); 22 of 190 true claims refused (11.6%).
- **Patched gate (f587183):** 56 of 273 accepted (20.5%, Wilson 16.1–25.7%); 30 of 190 refused (15.8%).
- **Rule not met.** The cut is 46%, short of the registered 50%, and the upper bound is above 10%. False refusals rose 4.2 points, within the 5-point limit.
- **What still gets through most:**
  - false absences (27 of 56);
  - numbers borrowed from another field (17 of 41).
- No further patch is credited against these attacks, since that would need a new held-out set.

### Change after the T18 freeze (2026-11-02)
The checker's sentence splitter no longer breaks a sentence at a decimal point ("3.9"). It is used to recheck saved agent cases against today's receipts. This change came after the freeze, so the T18 numbers above are the frozen gate's and are not rescored.

## T20 Muse Spark reads each claim, code checks it (registered 2026-11-02, before any model call)

- **Question:** does a model that reads each claim into checkable assertions catch the false claims the regex checker misses, without refusing more true ones?
- **Code:** `nearmisslens/claimcheck.py`; tests in `tests/test_claimcheck.py` (committed with this text).
- **Data:** every verified claim of the T18 held-out set (273 false, 190 true; Muse Spark Open, corners 21–30) with the receipts saved for it. Secondary: the T18 development set (194 false, 113 true). Neither set was used to write the T20 prompt.
- **Arms:**
  - (a) the regex checker frozen for T18 (commit f587183), with the verdicts already saved;
  - (b) Muse Spark (Meta Model API, contributor mode) lists each claim's assertions (quote, receipt field, stated value, kind including "none"), whether it states a cause or certainty, and any untied number; code verifies each against the receipt;
  - (c) both: a claim passes only if (a) and (b) both accept it.
- **Metrics:** attack success (verified false claims accepted) and false refusal (verified true claims refused) with Wilson 95% intervals, by error type.
- **Rule:** the combined arm (c) is credited if, on the held-out set, its attack success is at most half that of (a) and its false refusal is at most 10 points above (a)'s. Arm (b) alone is reported against (a) either way.
- **Budget:** under $1.

### T20 result (2026-11-02)
- **Registered result, held-out set:**
  - regex checker: 56/273 false claims accepted (20.5%), 30/190 true claims refused (15.8%);
  - Muse Spark reading plus code check: 5/273 (1.8%), 87/190 (45.8%);
  - both: 3/273 (1.1%), 102/190 (53.7%).
- **Rule not met:** false refusal rose by more than 10 points. Development set: regex 15/194 and 4/113; model 1/194 and 29/113; both 1/194 and 30/113.
- **Why true claims were refused.** Most refusals came from three bugs in our verification code, not from the model's readings:
  - dates were treated as "not a number" (64);
  - whole-percent rounding was too tight (part of 29);
  - the confidence level and the five-year window counted as untied numbers (most of 15).
  
  The rest are model errors: "contributing factor" read as causal (3), and p-values labelled "none" (8).
- **Post hoc, same saved readings, no new model calls:** with the three bugs fixed, the model arm accepts 7/273 (2.6%) and refuses 34/190 (17.9%); both arms together accept 4/273 (1.5%) and refuse 57/190 (30.0%). Because these fixes were made after seeing the readings, they get no credit here. T20b tests them fresh.

## T20b The fixed claim reading on a fresh attacker (registered 2026-11-02, before any attack was generated)

- **Attacks:** Muse Spark Open on Baseten, a new prompt style ("advocate") never used before, corners ranked 31–40 in New York (not used in T18 or T20). The same spec checks as T18 decide which claims count.
- **Arms:**
  - (a) the regex checker as of this commit;
  - (b) Muse Spark reading plus the fixed code check (`claimcheck.py` as of this commit);
  - (c) both.
- **Rule:** arm (b) is credited if its attack success is at most half of (a)'s and its false refusal is at most 5 points above (a)'s. Arm (c) is reported either way.
- **Budget:** under $2.

### T20b result (2026-11-02)
- regex 17/157 accepted, 45/89 refused; model 2/157, 24/89; both 1/157, 55/89; 114 attack claims dropped (spec did not check out).
- **Rule met:** the model arm's attack success (1.3%) is under half the regex arm's (10.8%), and its false refusal (27%) is lower than the regex arm's (51%), not higher.
