# Features and checklist

A box is ticked only when a unit test or a `nml selftest` row verifies the feature. "Built" means the code is done and tested with a scripted fake model. "Run" means it has produced real results on FLUID with the Meta Model API.

## The desk (real cases from the live world)
- [x] **Muse Spark orchestrator** (`orchestrator.py`, `nml desk SPEC`): Meta `web_search` to find the source, `read_page` for the text the citation gate checks, tool search over one deferred tool per registry dataset (generated from `registry.json`), `investigate` (the engineer's checked tools), `check_claim`, `program_record`, `view_photo`, a Muse Spark Open letter, and `check_findings` (a dry run of the gate). Verified by `tests/test_orchestrator.py`.
- [x] **Publish gate:** every record number is checked against its receipt (the gate names the right receipt when a finding cites the wrong one); a fact from the source must be on its page; a claim verdict must match its `check_claim` receipt; at least one quote must be verified; the site-check rule applies across receipts; no causal wording; no licence plate. Verified by `tests/test_orchestrator.py`.
- [x] **Honest claim verdicts:** consistent / differs from the record (with the record's 100 m, five-year frame) / cannot be checked / overstates. They are decided by the number checker, and model-read objections are shown as flags. Verified by `tests/test_orchestrator.py`.
- [x] **Address handling:** intersections in several written forms; an address goes to the nearest screened corner within 150 m or is refused; one intersection per case.
- [x] **Live 311 inbox** (`inbox.py`): San Francisco Open311 street reports with photos within 50 m of 5 or more injury crashes, saved once a day. A case cites the report's own record in the city's feed. Verified by `tests/test_review_fixes_3.py` (snapshots read by date).
- [x] **Registered runs, resumable and replayable** (`desk_runs.py`, specs in `validation/experiments/T21*.json`): limits, model check and inbox date come from the spec, and a replay miss stops the run instead of being recorded. Results: T21 4/12, T21b 5/12, T21c 11/12 (rule met), then T21d. Verified by `tests/test_review_fixes_3.py`.
- [x] **Baseline without the desk** (`baseline_desk.py`, `nml alone`, T24): Muse Spark with `web_search` alone on the same inputs, scored by code.
- [x] **Corner Watch** (`cameras.py`, `corner_watch.py`, T23): Seattle traffic cameras at the 40 camera corners with the most injury crashes. A frame is used only if it is inside the registry's daylight UTC hours (`cameras.daylight_utc_hours`) and brighter than `config.DARK_MEAN`. SAM 3.1 counts people and cars from frames packed into one video; Muse Spark points at layout features, and SAM must agree for "present" or "absent". Frames stay local. T23 ran on one morning's frames (06:00–07:42): packed counts met their rule; too few people were seen to rank corners. Verified by `tests/test_corner_watch.py` and `tests/test_review_fixes_3.py`.
- [x] **Desk page** on the site (saved runs, a static replay) (`#city/desk`): every case, every step, refusals with the gate's reasons, and each run's totals.

## The safety engineer
- [x] **Six checked tools with receipts** (`engineer.py`, `nml engineer`): screen the city, what the crashes have in common, what the city tried, the fix and its price, who must act, the request. Each returns its data with the datasets, as-of date, checks and seconds. Verified by `tests/test_engineer.py` and the selftest `engineer` row.
- [x] **Finish gate:** refuses a claim without a receipt, a number that is not the receipt's value for what its sentence names (a program, pattern, fix or year), a "none" the record contradicts, a per-year figure stated as a total, causal wording, and a site-check fix stated as supported; the summary is held to the same rules. The corner's own street numbers are places, and quoted police wording is the record's. Hardened by the T18 red team. Verified by `tests/test_engineer.py`.
- [x] **Agent mode** (`--agent`, `nml agent-cases CITY`): Muse Spark Open chooses the steps and writes the claims. Every refused attempt is kept and shown struck through on the corner page. Run on the top corners of 4 cities (results in README). Verified by `tests/test_engineer.py` (a refused attempt is recorded with its reasons).
- [x] **What the crashes have in common** (`rootcause.py`): one-sided binomial tests against the city's priority corners with a Holm correction, at least 10 crashes, fields the dataset lacks listed as not recorded. Verified by `tests/test_rootcause.py`.
- [x] **Who must act** (`jurisdiction.py`): road owners from the NYSDOT roadway inventory, inferred city streets marked, OpenStreetMap route tags as a designation-only fallback, offices from district maps. Verified by `tests/test_jurisdiction.py`.
- [x] **What the city tried** (`treatments.programs`): worked, earlier trend, not shown or worse for every tested program; a repeat-risk flag when a corner already got a program whose effect was not shown; a fix is ranked lower only when the city's interval rules out the national CMF. Verified by `tests/test_program_status.py`.
- [x] **CMF eligibility and evidence tiers:** 25 curated CMF Clearinghouse records. Control, crash population, kind of site (`only_for`) and preconditions (`site_condition`) must match. The pick is the FHWA-cited record, else the median (with an even count, the middle record with the smaller effect), never the largest. Each fix carries a tier: measured here, FHWA-cited, national studies, needs a site check, or contradicted here. Verified by `tests/test_cmf_eligibility.py`.
- [x] **Request letter to the owners,** copying the offices, salutations from the registry, every number label-checked. Verified by `tests/test_treatments.py` and `tests/test_engineer.py`.
- [x] **Pinned as-of date** (`validation/ASOF`) and an offline gazetteer, so replay gives the same answers on any later day. Verified by `tests/test_hygiene.py`.
- [x] **Static copilot** (`nml pages`, `docs/`): one engineer report per screened corner, checked for machine paths and key-like strings. Verified by `tests/test_hosting.py` and headless Chrome at desktop and phone width.
- [x] **Live endpoint hardening** (`app.py`, `budget.py`): bad JSON or points are 400, paths stay inside `docs/`, no request log, global daily caps on requests and model dollars. Verified by `tests/test_hosting.py`.
- [ ] **Hosted live endpoint on Modal** (`modal_web.py`): one container, a named secret, caps in a `modal.Dict`. Built; deployment waits for the go-ahead to make it public.

## Drone video: measurement
- [x] **Calibration:** video pixels to metres via homography to the base map. Verified by the selftest `calibration` row (median 0.31–0.39 m).
- [x] **Tracking (SAM 3.1):** tiled video tracking with 10 s windows, saturation splitting and one-to-one re-linking. Verified by `tracking_smoke` (vehicles: recall 0.77, precision 0.95) and `window_linking` (IDF1 0.99).
- [x] **Conflicts:** TTC and PET with FHWA SSAM definitions. Verified by `conflict_engine` and `tests/test_conflicts.py`.
- [x] **Routes and signal state on entry.** Verified by `routes` (route accuracy 0.947 / 0.947 / 0.955).
- [x] **Hotspots:** 15 m cells ranked by the exact Poisson 95% lower bound. Verified by `audit` and `tests/test_audit.py`.

## Falsification gates
- [x] **Causal gate, for any city in the registry** (`treatments.py`, `nml treatments`): a registered comparison-group before/after design, the rule, and placebo dates, for any dated program in the registry; designs are JSON files in `validation/studies/`. Verified by `tests/test_treatments.py` (recovers a planted effect, fails a program whose placebo drops, drops cohorts without comparisons) and by T11 reproducing exactly from its spec.
- [x] **Replication (T13):** Seattle's leading pedestrian intervals pass (−33%, placebos clean); DC, San Francisco and more New York programs are registered with the same design.
- [x] **Fake programs (T12):** 200 null programs; the gate credits 5.5% of them, a naive before/after 8.0%. Verified in `validation/BENCH.md`.
- [x] **AI analyst with and without the gate (T12 agentic arms):** Muse Spark Open writes and runs its own analysis code in a sandbox (Modal, or a local network-isolated fallback); the gated arm explores on half the sites and the gate decides on the other half. Run; results in `validation/BENCH.md` (T12 agentic arms).
- [x] **Registry-driven cities:** crash datasets, treatment programs, district offices, agencies and factor vocabularies are data in `registry.json`; no city is named in the engine's code.

## City plan, requests and the red team
- [x] **City action plan** (`plan.py`, `nml plan CITY`, each city's landing view): one supported low-cost fix per corner, the largest estimate of any tier kept apart, regression to the mean measured on the cases, one number-checked letter per road owner, CSV. Verified by `tests/test_plan.py`.
- [x] **Requests already denied** (`studyrequests.py`, registry kind `study_requests`): NYC signal study requests matched to corners by street names; a denied fix still missing, with pedestrians injured since, goes on a re-request list with a checked sentence. Verified by `tests/test_studyrequests.py`.
- [x] **Red team (T18)** (`redteam.py`): attacker models write false claims with specs code verifies; the patch was frozen before a held-out attacker. Verified by `tests/test_redteam.py`; results in `validation/BENCH.md`.
- [x] **CMF records read by Muse Spark (T19)** (`applicability.py`): where each CMF applies, with quotes the code checks, scored against hand labels. Verified by `tests/test_applicability.py`; results in `validation/BENCH.md`.
- [x] **README numbers tied to results:** `tests/test_readme_numbers.py` fails when a committed result and the README disagree.
- [x] **Continuous tests:** `.github/workflows/tests.yml` runs the suite on a fresh clone with no keys or downloads.

## Discovery, site check and questions
- [x] **Mechanism miner** (`miner.py`, NML-Bench T15): Muse Spark Open proposes crash mechanisms from the years before 2024-05-01, using the NYC vehicle and person tables (column names from registry roles). Code tests every proposal with Holm over all of them and confirms survivors once on later years the agent never sees. Grid and greedy arms run without a model, and 100 null corners measure false finds. Run on 100 corners: 0.02 false finds per null corner; comparable distinct mechanisms to the grid from 43× fewer tests; registered rule not met. Verified by `tests/test_miner.py` (the sealed years are hidden from the agent, every proposal counts in the correction, overclaiming wording is refused).
- [x] **Site check** (`sitecheck.py`, T16): Muse Spark reads the orthophoto and points; SAM 3.1 must confirm within 15 m. Ground truth comes from registry `site_truth` adapters (city layers, or OpenStreetMap anywhere), and the attributes are in `data/site_attributes.json`. Run on 304 corners: the registered rule is met for two attributes, but no attribute beats always giving the common answer, so none changes a recommendation (change 1). Verified by `tests/test_sitecheck.py`.
- [x] **Ask the engineer** (`askeng.py`, `POST /ask`, T17): Muse Spark Open answers a free question from the corner's saved receipts under the finish gate, and refused sentences are returned with the reason. On 40 questions: 0 wrong sentences shown with the gate, 31 without; 62.5% answered with the gate, 90% without. Verified by `tests/test_askeng.py` and `tests/test_hosting.py`.
- [x] **More cities by crash clusters** (`citywide.junctions_from_crashes`, registry `"screen": {"from": "crashes"}`): Seattle, Washington DC and San Francisco, the 50 worst injury-crash clusters each, named from OpenStreetMap streets, with no model cost.

## Briefs, screens and studies
- [x] **Safety Brief for an address in a registry city** (`nml brief`): official crash record, city designations and recorded treatments, eligible FHWA countermeasures ranked by expected crashes avoided (CMF method), dollar values, aerial and street photos, a checked memo.
- [x] **Checked memo:** code builds the ranking; the agent writes the narrative; a checker rejects any number not in the facts. Verified by T8 (0 of 34 ungrounded with the checker vs 4 of 34 without).
- [x] **Open-data registry and data agent** (`nml discover`): a city's crash data as a validated adapter (the city is added first with `nml add-city`); validator inside the agent's tool. Run on Seattle (no hand-written support): adapter accepted after two validator refusals.
- [x] **Citywide screen** (`nml citywide`): all 304 NYC Vision Zero priority intersections; 225 plan gaps; injury crashes counted once each (11,477 at the pinned date) and costed at the U.S. DOT value ($786 million a year). Verified by T9 in `validation/BENCH.md`.
- [x] **Did the city's fixes work?** (`treatments.py`, `nml treatments`): comparison-group before/after study of 1,651 NYC Leading Pedestrian Interval sites against sites treated later, with a placebo date; pedestrian injury crashes −17% (95% interval 11–22%), placebo null. Turn calming not credited (placebo fails). Verified by T11 in `validation/BENCH.md` and `tests/test_treatments.py` (recovers a planted effect).
- [x] **Dollar values for every fix** (`harm.py`): U.S. DOT BCA Guidance 2026 Update, Table A-1 ($342,400 per injury crash, 2024 $), break-even cost over 10 years at 7%. Verified by `tests/test_treatments.py`.
- [x] **Fix illustration on the city's aerial photo:** Muse Image edit composited around the junction, real road users protected by SAM 3.1 masks, SAM 3.1 check. 13 of 20 pass on the top-20 briefs.
- [x] **Copilot** (`nml app` locally, `docs/` on Pages): map of the screened corners, search, the engineer's case for each. Verified by headless Chrome screenshots.
- [x] **What the city tried** and **receipts** on every case (which check verified which claim).
- [x] **Letters** (`letter.py`, `nml brief --letter`, the app's "Draft a letter"): addressed to the council district and community board from the city's district maps; every number checked; sources added by code. Verified by `tests/test_treatments.py` (an invented number is refused).
- [x] **Voice studio** (`nml voice-studio`): the narrator records each demo line in the browser; `nml demo --copilot` uses the takes.
- [x] **Open-weights tier:** Muse Spark Open (Baseten) runs the engineer agent, the analyst and the letters. Muse Glimmer (Modal GPU) was compared on complaint checking only (T4, 87.5%).
- [x] **Near-miss and crash fusion** (`fusion.py`): negative binomial + Empirical Bayes with near-miss counts; tested on held-out DC blocks and future years (T10, negative result for residents' reports).

## Decision support
- [x] **Countermeasures:** FHWA Proven Safety Countermeasures with CMF Clearinghouse citations, checked against road user, site control and observed condition. Verified by `audit` and `tests/test_countermeasures.py`.
- [x] **Audit memo:** every number traced to the data, with rejections listed. Command: `nml audit`. Verified by `tests/test_audit.py`.
- [x] **Video review (Muse Spark):** verdicts on event clips. Verified by the `verifier` row.
- [x] **Review panel, built:** Proposer (Muse Spark), Skeptic (Muse Spark) and Arbiter (Muse Wonder). Command: `nml panel`. Verified by `tests/test_panel.py`.
- [x] **Grounding checker:** rejects fabricated CMF ids, rejected countermeasures, missing hotspots and invented numbers on the real dev audit. Verified by the `grounding` row.
- [x] **Fix illustration (Muse Image + SAM 3.1 check), built:** road users protected, edit checked by SAM. Verified by `tests/test_render.py`.
- [x] **Review panel run** on the test and held-out SAM audits. The Arbiter rejected recommendations the video review showed were tracking artefacts or mismatches (`runs/audit/*_sam/panel.md`).
- [x] **Fix illustration run:** 5 of 6 pass the SAM 3.1 check on the current audits.
- [x] **Voice complaints, built:** Muse Voice Transcribe, then Muse Spark extraction, then a fixed matching rule. Synthetic complaints in 3 languages are spoken by MMS-TTS. Verified by `tests/test_voice.py`.
- [x] **Voice complaints run:** 8 of 8 synthetic complaints matched correctly (English, Spanish, French, plus decoys). Mean word error rate 7–13%.
- [x] **Signal-entry chart:** red and yellow entries by approach and road-user class. Verified by `tests/test_export.py`; shown in the viewer's "Who enters on red" section.

## Validation (rules registered in `validation/PREREG.md`)
- [x] **Two-wheeler experiment (change 8, dev only):** negative result. No prompt or tile size met the registered rule.
- [x] **Track stitching (change 9):** two-wheeler IDF1 0.46→0.54 on test and 0.37→0.42 on held-out. Reported next to the registered numbers.
- [x] **Signal-entry evidence (change 7):** limited to vehicles for SAM tracks after the agreement check. Disclosed as decided after the test run.
- [x] Splits fixed before any test or held-out run: dev, test, and held-out intersection.
- [x] **Evaluation of test and held-out:** written to `validation/RESULTS.md`. Dev was used for development only.
- [x] **B0 baseline, built:** scorer and windows as registered. Verified by `tests/test_baseline.py`.
- [x] **B0 run:** near-miss F1 is 0.32 for the pipeline against 0.02 for Muse Spark alone.
- [x] **Verifier precision-gain test, built:** command `nml verifier`.
- [x] **Verifier run:** precision 0.69 for events rated real, against 0.46 for the severity ranking at matched recall.

## Display
- [x] **Drone-video viewer (`docs/video/`):** hotspot map, case-file rail, memo and scorecard. Data comes from `nml export`. Verified by `tests/test_export.py` and headless Chrome screenshots at desktop and phone width (no horizontal scroll).
- [x] **3D replay of top conflicts:** three.js, measured positions, sizes and headings; heights are schematic. Verified by a headless WebGL screenshot.
- [x] **Panel debate view:** shows real panel runs.
- [x] **Scorecard:** generated from the self-test and `RESULTS.md`.

## Offline and open weights
- [x] Replay mode: every paid result is cached, and `nml --replay ...` costs nothing. Verified by the `selftest` replay run.
- [x] Muse Glimmer served on a Modal L4 GPU (`nearmisslens/glimmer_modal.py`): its Q4 weights need more than this PC's 16 GB, so it runs on partner hardware, not locally.

## Submission
- [x] **README** with quick start, Meta tools table and "built during the hackathon".
- [x] **LICENSES.md and PRIVACY.md.**
- [x] **Data download:** `nml fetch` reads clips out of remote ZIP64 archives with resumable range requests and a CRC32 check, verifies MD5s, and completes the CMF server's certificate chain from its AIA URL. Verified by `tests/test_fetch.py`.
- [x] **Demo video renderer, built:** `nml demo` records the viewer with headless Chrome, adds the reviewed event clip with Spark's verdict, and makes title cards from run outputs. A trial render on dev data was checked frame by frame.
- [x] Earlier demo video (2:09, Kokoro guide voice) and a 20 s X cut on the v2.0 release.
- [ ] Final demo re-scripted around the engineer (`nml demo --copilot`), narrated by the author (`nml voice-studio`).
- [x] Replay cache published as a release asset (v2.0).
- [ ] Replay cache refreshed for the engineer (`nml pack-cache`: contact details removed, refused if a key is found).
- [x] No keys in the tree, the git history, the replay cache or run outputs (scanned for every key value in `.env` and the Modal token).
- [ ] Repo public, Pages live.
- [ ] Submitted on the portal before Nov 4, 12:00 Dhaka.

## How to check
```bash
nml --replay selftest   # exit 0 only if every row passes; 3 if a row could not be checked
pytest -q               # all unit tests pass
nml cost                # Meta API spend so far
```
