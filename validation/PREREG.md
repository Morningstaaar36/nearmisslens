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
None yet.
