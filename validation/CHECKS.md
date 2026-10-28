# Kill-checks

| ID | Check | Result | Cost |
|---|---|---|---|
| K1 | `/v1/status`, `/v1/models` | operational; sam-3.1, muse-spark-1.3(-contributor), muse-wonder-1.0, muse-image-1.0, muse-voice-transcribe-1.0 listed | $0 |
| K2 | SAM 3.1 image on FLUID dev frame 601 (3840×2160), matched to reference centres (40 px) | car: 29/32 recall, 29/33 precision; "scooter": 16/17 recall, 16/18 precision; "moped": 0 detections; "pedestrian": 0/2; 2×2 tile did not improve recall | $0.04 |
| K3 | SAM 3.1 video, 10 s dev clip (100 frames, H.264 4K) | car: 16 ids, median 13 per frame (reference about 32): the 16-object cap binds at full frame; scooter: 6 ids. 48 s and 13 s wall-clock | $0.04 |
| C1 | Calibration: video frame 100 → base map (SIFT + RANSAC homography) → metres, against 2,000 FLUID pixel↔metre reference pairs (evaluation only) | dev 0.39 m median / 1.61 m p90; test 0.32 / 0.94; held-out FI 0.31 / 0.53 | $0 |
| E1 | Conflict engine on FLUID dev reference trajectories (6.8 min) | 155 TTC ≤ 1.5 s events (34 at ≤ 0.5 s); PET ≤ 1.5 s crossing pairs: 242, of which 122 two-wheeler–two-wheeler; TTC run 8 s, PET 7 s | $0 |
| T1 | SAM 3.1 API video ("car", "scooter") on dev 60–70 s → calibrated, smoothed tracks vs FLUID reference (2 m / 1.5 m match) | vehicle: precision 0.985, recall 0.397, position RMSE 0.57 m, speed MAE 0.16 m/s, 0 ID switches; two-wheeler: precision 0.97, recall 0.18, RMSE 0.65 m, speed MAE 0.38 m/s. Recall is limited by the 16-objects-per-frame cap | $0 (cached) |
| T2 | Same 10 s clip, 2×2 overlapping tiles per concept, merged | vehicle: recall 0.772, precision 0.912, RMSE 0.56 m, speed MAE 0.27 m/s, IDF1 0.84; two-wheeler: recall 0.604, precision 0.82, RMSE 0.32 m, speed MAE 0.18 m/s, IDF1 0.70 | $0.16 |
| K4 | Muse Spark 1.3 (Contributor) verifies event-centred crops (1280×720, ±3 s, both users outlined, plus speed-trace image) with a strict JSON schema; 3 lowest-TTC mixed-class reference events from dev | all 3 returned valid JSON; 2 with braking and the yielding user identified; one reference "pedestrian" identified as "visibly a motorized two-wheeler" (a reference label error). About 2,000 input tokens per event, 13–18 s, $0.0004–0.0006 per event | $0.0013 |
