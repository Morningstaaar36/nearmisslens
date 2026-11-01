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
