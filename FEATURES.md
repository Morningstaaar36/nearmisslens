# Features and checklist

A box is ticked only when a unit test or a `nml selftest` row verifies the feature. "Built" means the code is done and tested with a scripted fake model. "Run" means it has produced real results on FLUID with the Meta Model API.

## Measurement
- [x] **Calibration:** video pixels to metres via homography to the base map. Verified by the selftest `calibration` row (median 0.31–0.39 m).
- [x] **Tracking (SAM 3.1):** tiled video tracking with 10 s windows, saturation splitting and one-to-one re-linking. Verified by `tracking_smoke` (vehicles: recall 0.77, precision 0.95) and `window_linking` (IDF1 0.99).
- [x] **Conflicts:** TTC and PET with FHWA SSAM definitions. Verified by `conflict_engine` and `tests/test_conflicts.py`.
- [x] **Routes and signal state on entry.** Verified by `routes` (route accuracy 0.947 / 0.947 / 0.955).
- [x] **Hotspots:** 15 m cells ranked by the exact Poisson 95% lower bound. Verified by `audit` and `tests/test_audit.py`.

## Decision support
- [x] **Countermeasures:** FHWA Proven Safety Countermeasures with CMF Clearinghouse citations, checked against road user, site control and observed condition. Verified by `audit` and `tests/test_countermeasures.py`.
- [x] **Audit memo:** every number traced to the data, with rejections listed. Command: `nml audit`. Verified by `tests/test_audit.py`.
- [x] **Video review (Muse Spark):** verdicts on event clips. Verified by the `verifier` row.
- [x] **Review panel, built:** Proposer (Muse Spark), Skeptic (Muse Spark) and Judge (Muse Wonder). Command: `nml panel`. Verified by `tests/test_panel.py`.
- [x] **Grounding checker:** rejects fabricated CMF ids, rejected countermeasures, missing hotspots and invented numbers on the real dev audit. Verified by the `grounding` row.
- [x] **Fix illustration (Muse Image + SAM 3.1 check), built:** road users protected, edit checked by SAM. Verified by `tests/test_render.py`.
- [x] **Review panel run** on the test and held-out SAM audits. The Judge rejected recommendations the video review showed were tracking artefacts or mismatches (`runs/audit/*_sam/panel.md`).
- [x] **Fix illustration run:** 5 of 6 pass the SAM 3.1 check on the current audits.
- [x] **Voice complaints, built:** Muse Voice Transcribe, then Muse Spark extraction, then a fixed matching rule. Synthetic complaints in 3 languages are spoken by MMS-TTS. Verified by `tests/test_voice.py`.
- [x] **Voice complaints run:** 8 of 8 synthetic complaints matched correctly (English, Spanish, French, plus decoys). Mean word error rate 7–13%.
- [x] **Signal-entry chart:** red and yellow entries by approach and road-user class. Verified by `tests/test_export.py`; shown in the viewer's "Who enters on red" section.

## Validation (pre-registered in `validation/PREREG.md`)
- [x] **Two-wheeler experiment (change 8, dev only):** negative result. No prompt or tile size met the registered rule.
- [x] **Track stitching (change 9):** two-wheeler IDF1 0.46→0.54 on test and 0.37→0.42 on held-out. Reported next to the registered numbers.
- [x] **Signal-entry evidence (change 7):** limited to vehicles for SAM tracks after the agreement check. Disclosed as decided after the test run.
- [x] Splits fixed before any test or held-out run: dev, test, and held-out intersection.
- [x] **Evaluation of test and held-out:** written to `validation/RESULTS.md`. Dev was used for development only.
- [x] **B0 baseline, built:** scorer and windows as pre-registered. Verified by `tests/test_baseline.py`.
- [x] **B0 run:** near-miss F1 is 0.32 for the pipeline against 0.02 for Muse Spark alone.
- [x] **Verifier precision-gain test, built:** command `nml verifier`.
- [x] **Verifier run:** precision 0.69 for events judged real, against 0.46 for the severity ranking at matched recall.

## Display
- [x] **Viewer (GitHub Pages, `docs/`):** hotspot map, case-file rail, memo and scorecard. Data comes from `nml export`. Verified by `tests/test_export.py` and headless Chrome screenshots at desktop and phone width (no horizontal scroll).
- [x] **3D replay of top conflicts:** three.js, measured positions, sizes and headings; heights are schematic. Verified by a headless WebGL screenshot.
- [x] **Panel debate view:** shows real panel runs.
- [x] **Scorecard:** generated from the self-test and `RESULTS.md`.

## Offline and open weights
- [x] Replay mode: every paid result is cached, and `nml --replay ...` costs nothing. Verified by the `selftest` replay run.
- [ ] Muse Glimmer offline answers (subject to a 2-hour feasibility check).

## Submission
- [x] **README** with quick start, Meta tools table and "built during the hackathon".
- [x] **LICENSES.md and PRIVACY.md.**
- [x] **Data download:** `nml fetch` reads clips out of remote ZIP64 archives with resumable range requests and a CRC32 check, verifies MD5s, and completes the CMF server's certificate chain from its AIA URL. Verified by `tests/test_fetch.py`.
- [x] **Demo video renderer, built:** `nml demo` records the viewer with headless Chrome, adds the reviewed event clip with Spark's verdict, and makes title cards from run outputs. A trial render on dev data was checked frame by frame.
- [ ] Final 3-minute demo video from the paid runs, plus a 20 s X cut.
- [ ] Replay cache published as a release asset, so `--replay` works from a clean clone (`cache/` is gitignored).
- [ ] Repo public, Pages live, no keys in history.
- [ ] Submitted on the portal before Nov 4, 12:00 Dhaka.

## How to check
```bash
nml --replay selftest   # every row PASS, free and offline
pytest -q               # all unit tests pass
nml cost                # Meta API spend so far
```
