# Kill-checks

| ID | Check | Result | Cost |
|---|---|---|---|
| K1 | `/v1/status`, `/v1/models` | operational; sam-3.1, muse-spark-1.3(-contributor), muse-wonder-1.0, muse-image-1.0, muse-voice-transcribe-1.0 listed | $0 |
| K2 | SAM 3.1 image on FLUID dev frame 601 (3840×2160), matched to reference centres (40 px) | car: 29/32 recall, 29/33 precision; "scooter": 16/17 recall, 16/18 precision; "moped": 0 detections; "pedestrian": 0/2; 2×2 tile did not improve recall | $0.04 |
| K3 | SAM 3.1 video, 10 s dev clip (100 frames, H.264 4K) | car: 16 ids, median 13 per frame (reference about 32): the 16-object cap binds at full frame; scooter: 6 ids. 48 s and 13 s wall-clock | $0.04 |
| C1 | Calibration: video frame 100 → base map (SIFT + RANSAC homography) → metres, against 2,000 FLUID pixel↔metre reference pairs (evaluation only) | dev 0.39 m median / 1.61 m p90; test 0.32 / 0.94; held-out FI 0.31 / 0.53 | $0 |
| E1 | Conflict engine on FLUID dev reference trajectories (6.8 min) | 155 TTC ≤ 1.5 s events (34 at ≤ 0.5 s); PET ≤ 1.5 s crossing pairs: 242, of which 122 two-wheeler–two-wheeler; TTC run 8 s, PET 7 s | $0 |
