# Pre-registration: NearMissLens validation on FLUID

Committed before any tracking run on the test or held-out clips. Only the development clip has been used to build and tune the pipeline. Anything changed after this commit is listed at the end, with a reason.

## Data
- FLUID dataset (Scientific Data 2026; figshare 10.6084/m9.figshare.29974954 v2; CC BY 4.0).
- Stabilised top-down drone video, HEVC 3840×2160 at 10 fps.
- Reference trajectories come from the authors' trained YOLOv8-OBB + SparseTrack pipeline. They are a reference, not ground truth, and results are reported as **agreement**.

| Split | Clip | Use |
|---|---|---|
| Development | FIDRT `20250525_video` (4,074 frames) | building and tuning; reported separately |
| Test | FIDRT `20250526_video`, frames 1–6,000 (first 10 min) | headline numbers |
| Held-out site | FI `20250530_video-1` (5,352 frames) | a different intersection, never seen during development |

- The authors' human counts cover minutes 0–5 of the test clip (MV 281 / VRU 196). They are the only true ground truth, used for counts only.
- If compute or budget allows, the rest of the test clip is reported as an extension, labelled as such.

## Classes
- **vehicle:** FLUID car, van, truck, bus, tricycle, trailer.
- **two-wheeler:** FLUID moped. SAM concept "scooter" (chosen on dev frame 601; "moped" returned no detections).
- **pedestrian:** FLUID pedestrian. A SAM person or pedestrian mask overlapping a two-wheeler mask is a rider and is dropped.
- Pedestrian-only conflict results are descriptive if fewer than 20 reference events exist.

## Geometry
- Our position is the centre of each SAM mask's minimum-area rectangle, mapped to metres by a homography from one video frame to the site's metric base map (SIFT + RANSAC).
- The reference position is FLUID `cx_m, cy_m`.
- Only reference points with `isReal == 1` are scored for tracking.
- Calibration is reported against FLUID's pixel↔metre pairs. These are used for evaluation only, never as input.

## Tracking metrics (per class)
- Frame-wise Hungarian matching on metric distance, with thresholds vehicle 2.0 m, two-wheeler 1.5 m, pedestrian 1.0 m.
- Reported:
  - recall and precision of track points;
  - position RMSE;
  - speed MAE and bias, against FLUID `speed`;
  - IDF1, using majority mapping;
  - ID switches per minute.

## Conflicts
The same engine (`nearmisslens/conflicts.py`) runs on our tracks and on the reference tracks.

- **TTC events:**
  - constant-velocity projection of oriented rectangles, horizon 3 s, step 0.1 s;
  - event = maximal interval per pair with 0 < TTC ≤ 1.5 s (FHWA SSAM default);
  - the gap between frames inside an event is at most 5 frames;
  - type by SSAM's angle rule (rear-end < 30°, crossing > 85°, otherwise lane change);
  - severity bands TTC ≤ 0.5 / 1.0 / 1.5 s.
- **Artefact filter (both sides):** closing speed > 1 m/s and both users moving > 0.5 m/s. Pairs already overlapping at the first projected step are excluded.
- **PET:** a 0.5 m grid; paths crossing at ≥ 30°; PET ≤ 5.0 s. Reported separately, with PET ≤ 1.5 s and ≤ 3.0 s bands.
- **Event matching:** our event matches a reference event when our two tracks map (by majority track matching) to the reference pair and the frame intervals overlap within ±10 frames (1 s). Matching is one-to-one.
- **Reported:**
  - precision, recall and F1 per type and per class pair (vehicle–vehicle, vehicle–two-wheeler, vehicle–pedestrian, two-wheeler–pedestrian, two-wheeler–two-wheeler);
  - Kendall τ of hotspot ranking, by approach pair (`overall_direction` of the reference users).
- **Secondary comparison:** FLUID's own conflict table (motor vehicles only, TTC ≤ 2.0 s / DGT ≤ 4.0 s, TTC column only), after the same artefact filter.

## Verifier and baselines
- **Spark verifier** (`muse-spark-1.3-contributor`, reasoning effort low) on every candidate event. Reported:
  - precision gain at matched recall, against reference events;
  - the share of events it marks as artefacts;
  - cost per event.
- **B0, bare model:** Muse Spark watches 60 ten-second windows of the test clip and lists near-misses with times and road-user types. It is scored at event level (±1 s, type).
- **Agent steering:** Wonder chooses where to spend tiled SAM passes under a fixed budget, against uniform tiling at the same budget, on the held-out site. Metric: conflict recall per dollar (or per GPU-minute).

## Frozen parameters
SAM concepts "car" and "scooter" for API runs; 2×2 tiles with 128 px overlap; Savitzky–Golay window 11, order 2; the thresholds above.

## Changes after registration
Made before any test or held-out run, after a literature review (`research/R6_papers.md`):

1. **Smoothing.** Velocities are now Savitzky–Golay derivatives of the raw positions, not of already-smoothed positions. Each track is split at gaps longer than 3 frames, and shorter gaps are filled by linear interpolation. This fixes a double-smoothing and gap defect.
2. **PET footprint.** Cells are those whose centres lie inside the oriented rectangle, not its axis-aligned bounding box. The old version biased PET for diagonal vehicles.
3. **Headline measure.** PET (crossing and turning paths) is the headline conflict measure, and TTC is secondary. Tracker-derived TTC is known to be biased towards less safe (Liu, Saunier & Bilodeau, Transportation Research Part C 2026). In a visual review, 47% of TTC-flagged events were data errors, against 3% for PET (Steinmaßl et al., Traffic Safety Research 2025).
4. **No crash-frequency estimates.** Extreme value theory needs 15 to more than 45 hours per site (Zheng et al., Accident Analysis & Prevention 2025), so we report no crash frequencies.
5. **Tracking windows.** SAM 3.1 video requests return at most 16 distinct objects per request, a cap we confirmed on cached responses: no response held more than 16 object ids. Dense scenes therefore lost tracks inside 61 s windows. Tracking now uses 10 s windows with 0.5 s overlap. A window whose response reaches the cap is split in time, down to the 50-frame API minimum, and the pieces are re-linked by one-to-one assignment on the overlap frames. Windows are joined by one-to-one Hungarian assignment on position votes. The self-test `window_linking` checks the re-linking by cutting the reference tracks into windows with fresh ids and 0.3 m noise and requiring vehicle IDF1 ≥ 0.9. The dev numbers measured with 61 s windows are superseded, and no test or held-out run had been made.
6. **Verifier and B0 scoring, made precise.** Recorded before any test or held-out run.
   - **Event matching:** an event matches a reference conflict when it has the same unordered pair of road-user classes and its time is within 1 s. Matching is one to one, minimising total time difference. The reference is the conflict table built by `audit.conflict_table` from the reference trajectories: one row per pair, PET ≤ 1.5 s or TTC ≤ 1.5 s.
   - **Verifier at matched recall:** "precision gain at matched recall" compares two sets at equal recall:
     - the events Muse Spark rates real;
     - the smallest set of most severe candidates (lowest PET or TTC) that reaches the same recall, which is the no-model ranking.
   - Precision and recall before filtering are reported as well.
7. **Signal state on entry, decided after the test and held-out runs and disclosed as such.**
   - **Observed entry:** a track that begins inside the 20 m entry radius, for example a fragment of a broken track, now has no entry time. Before, the fragment's start counted as its entry.
   - **Evidence with SAM 3.1 tracks:** these tracks match the reference on vehicles. On two-wheelers they over-count red entries, probably because riders waiting in dense queues are missed more often than lone riders running the light. With SAM tracks, only vehicle entries now count as evidence for "an entry on yellow or red". Reference audits keep both classes.
   - **Where the numbers are:** the agreement table per split is in `validation/results/<split>/signal_entry.json` and in RESULTS.md.
8. **Two-wheeler experiment on the development clip, registered before it was run.**
   - **Why:** after the test and held-out runs, two-wheeler recall (0.59 test, 0.36 held-out) limits conflict agreement, while vehicles are tracked well. Only 8% of the cached SAM 3.1 requests reached the 16-object cap, so small apparent size is the likely cause.
   - **Variants:** on development frames 601–1200 (60–120 s), each scored against the reference:
     - "scooter", "motorcycle", "motorbike" and "person riding a scooter" with the 2×2 tiles;
     - "scooter" with 3×3 tiles.
   - **Rule:** a variant replaces "scooter" with 2×2 tiles only if its two-wheeler recall is at least 0.10 higher and its precision is no more than 0.05 lower.
   - **If a variant wins:** test and held-out are tracked again for two-wheelers only. RESULTS.md then reports both the registered numbers and the new ones.
   - **Outcome (dev, frames 601–1200):** two-wheeler recall was:
     - "scooter" 2×2 tiles, 0.576 (precision 0.863);
     - "motorcycle", 0.640 (precision 0.874);
     - "motorbike", 0.472;
     - "person riding a scooter", 0.000;
     - "scooter" 3×3 tiles, 0.339 (precision 0.748).

     No variant met the rule, so "scooter" with 2×2 tiles stays and test and held-out are not re-tracked. Results are in `validation/results/dev/two_wheeler_experiment.json`.
9. **Track stitching, registered after evaluation on the development clip only.**
   - **Rule:** a SAM 3.1 track that ends is continued by a same-class track that starts within 1.5 s. The start must lie within 3 m of the position predicted from the first track's final velocity. Ends and starts are paired one to one by Hungarian assignment.
   - **Dev effect, frames 601–1200, "scooter":**
     - two-wheeler IDF1 0.562 → 0.623;
     - ID switches 33 → 21 per minute;
     - recall and precision unchanged.

     Settings tried: 0.5 s/1.5 m, 1 s/2 m, 1.5 s/3 m and 2 s/3 m. The gain levels off after 1.5 s/3 m.
   - **Older dev window, frames 1–1810:**
     - vehicles unchanged;
     - two-wheeler IDF1 0.485 → 0.500.
   - **Reporting:** test and held-out are re-scored from the same cached tracks, with no new tracking. RESULTS.md reports the registered numbers and the stitched numbers side by side. The audits use stitched tracks from now on.
10. **Robust kinematics, registered after the test and held-out runs and disclosed as such.**
   - **Why:** a diagnostic on cached tracks (`research/R11_recall_waterfall.md`) found that velocity noise dominates the disagreement on tracked pairs. Error is 0.53 m/s within 5 frames of a Savitzky–Golay segment edge against 0.07 m/s inside, and 937 test rows imply speeds above 15 m/s. That diagnostic used the test split, so test and held-out are no longer untouched for this change.
   - **Method:** a constant-velocity Kalman filter per track (`tracks.kalman_states`) with:
     - innovation gating (rejected measurements are skipped, and a run of rejections restarts the track);
     - gaps bridged by prediction instead of splitting segments;
     - an RTS smoother;
     - a per-class size-bias correction.
   - **Tuning rule:** parameters are chosen on the development clip only (frames 1–1810, the cached 61 s-window tracks) by mean vector velocity error at matched points (`evaluate.tune_kinematics`). Conflict scores are never used to choose them. The grid and the choice are in `validation/results/dev/kinematics_tuning.json`.
   - **Reporting:** test and held-out are re-scored once from the same cached tracks, with stitching, next to the registered and stitched numbers. The clean test of this change is change 11.
11. **Fresh-flight confirmation (NML-Bench), registered before any of these flights was tracked or scored.**
   - **Flights:** the 11 FLUID flights never used so far: FIDRT 20250120; FI 20250120, 20250121-1/2/3, 20250525-1/2, 20250530-2; TI 20250529-1/2/3. TI is a third junction never seen.
   - **Window:** seconds 120–180 of each flight (frames 1201–1800). The rule was fixed before any of these videos was viewed.
   - **Pipeline, frozen:** SAM 3.1 "car" and "scooter", 2×2 tiles, 10 s windows, stitching (change 9), and the kinematics chosen in change 10. v0 (Savitzky–Golay) is scored on the same tracks as the comparison.
   - **Metrics:**
     - tracking per class;
     - TTC event F1 and recall-weighted F2 = 5TP/(5TP+4FN+FP) (USDOT Intersection Safety Challenge);
     - PET ≤ 1.5 s and ≤ 3.0 s F1;
     - recall on tracked classes (pairs without a pedestrian) as a secondary metric.
   - **Rule:** v1 is reported as better than v0 only if pooled TTC F1 is higher and a 95% bootstrap interval over flights (2,000 resamples, seed 0) for the difference excludes zero. Otherwise both are reported and no improvement is claimed.
   - **Cost:** about $0.17 per 10 s (2 concepts × 4 tiles), about $11–12 for the 11 minutes. It runs only after the user approves the estimate.
