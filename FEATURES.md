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
- [ ] Review panel, run on the test and held-out audits.
- [ ] Fix illustration, run on real hotspots.
- [ ] Voice complaints (Muse Voice Transcribe), matched to measured hotspots.
- [ ] Signal-entry chart: red and yellow entries by approach and road-user class.

## Validation (pre-registered in `validation/PREREG.md`)
- [x] Splits fixed before any test or held-out run: dev, test, and held-out intersection.
- [ ] Evaluation of dev, test and held-out, written to `validation/RESULTS.md`.
- [ ] B0 baseline: Muse Spark alone watching the video, compared with the pipeline.
- [ ] Verifier precision gain against reference events.

## Display
- [ ] Viewer (GitHub Pages): hotspot map, memo and before/after.
- [ ] 3D replay of top conflicts (three.js, measured boxes).
- [ ] Panel debate view, showing the claims the checker caught.
- [ ] Scorecard page generated from `RESULTS.md`.

## Offline and open weights
- [x] Replay mode: every paid result is cached, and `nml --replay ...` costs nothing. Verified by the `selftest` replay run.
- [ ] Muse Glimmer offline answers (subject to a 2-hour feasibility check).

## Submission
- [ ] README with quick start and "built during the hackathon".
- [ ] LICENSES.md (FLUID CC BY 4.0, CMF Clearinghouse, FHWA) and PRIVACY.md.
- [ ] 3-minute demo video rendered from real outputs, plus a 20 s X cut.
- [ ] Repo public, Pages live, no keys in history.
- [ ] Submitted on the portal before Nov 4, 12:00 Dhaka.

## How to check
```bash
nml --replay selftest   # every row PASS, free and offline
pytest -q               # all unit tests pass
nml cost                # Meta API spend so far
```
