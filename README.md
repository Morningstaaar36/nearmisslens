# NearMissLens

An AI road-safety audit agent. It finds the near-misses that never reach crash data in ordinary top-down traffic video, checks its measurements against reference trajectories, and turns them into a cited fix, illustrated on the real junction.

Built during the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026). Every line of code in this repository was written during the hackathon.

## What it does
1. **Track:** SAM 3.1 tracks every car, scooter and person in the video, using tiled requests to the Meta Model API. Pixels are mapped to metres through a homography to the site's base map.
2. **Measure:** time-to-collision (TTC) and post-encroachment time (PET) are computed with FHWA SSAM definitions. A conflict is PET or TTC ≤ 1.5 s.
3. **Rank:** hotspots are 15 m cells ranked by the lower bound of the exact Poisson 95% interval on conflicts per 1,000 road users.
4. **Explain:** each road user's approach and turning movement, and the signal state when it entered, become evidence for the countermeasure match.
5. **Recommend:** only FHWA Proven Safety Countermeasures are recommended, each cited to a CMF Clearinghouse record whose crash type, road users, site control and condition fit what was observed. Rejections are listed with reasons.
6. **Review:** a panel of agents argues the recommendations. A Proposer (Muse Spark) suggests, a Skeptic (Muse Spark) objects with evidence, and a Judge (Muse Wonder) decides and writes the memo. A deterministic checker rejects any hotspot, CMF ID or number that is not in the data, and the agent must correct it.
7. **Verify and illustrate:** Muse Spark watches event-centred video of the worst conflicts. Muse Image draws the countermeasure on the real frame, with real road users protected by SAM masks, and SAM 3.1 checks that the edit added it.
8. **Listen:** a spoken complaint is transcribed by Muse Voice Transcribe. Muse Spark extracts road users, movement and approach, and a fixed rule matches it to a measured hotspot or reports that the audit does not show it.

## Meta AI tools and what each does
| Tool | Role | Where |
|---|---|---|
| SAM 3.1 (video) | Tracks all road users with masks from text prompts | `tiling.py`, `pipeline.py` |
| SAM 3.1 (image) | Protects road users in the illustration, and checks the edit | `render.py` |
| Muse Spark | Reviews conflict video, sits on the review panel, extracts complaints, runs the B0 baseline | `verifier.py`, `panel.py`, `voice.py`, `baseline.py` |
| Muse Wonder | Judges the review panel; plans tracking under a budget | `panel.py`, `conductor.py` |
| Muse Image | Before/after illustration of the countermeasure | `render.py` |
| Muse Voice Transcribe | Turns spoken complaints into text | `voice.py` |
| MMS-TTS (open weights) | Speaks the synthetic test complaints locally | `complaints.py` |

## Quick start
```bash
uv sync                      # Python 3.12; add --extra voice for MMS-TTS
uv run nml fetch             # FLUID clips and derived data, CMF Clearinghouse table (about 2 GB)
uv run nml --replay selftest # every check recomputed from the data; no API calls
uv run nml audit dev         # audit memo from FLUID reference trajectories; free
uv run nml export dev        # viewer data, then: python -m http.server -d docs
```
Model calls need `MODEL_API_KEY` in the environment. Every paid command prints its maximum cost first, stops at the cap in `NML_BUDGET_USD` (default $60), and caches every response. `--replay` serves only from the cache and never calls the API.

| Command | What it does |
|---|---|
| `nml audit SPLIT [--source sam] [--verify N] [--illustrate]` | Conflicts, hotspots, cited countermeasures; optional video review and illustration |
| `nml panel SPLIT` | Proposer, Skeptic and Judge review an audit, held to the data by the checker |
| `nml voice SPLIT [--audio FILE]` | Match a recording to the hotspots, or test on synthetic complaints |
| `nml evaluate SPLIT...` | Track the pre-registered splits with SAM 3.1 and score against the reference |
| `nml verifier SPLIT` | Muse Spark reviews every candidate conflict; precision before and after |
| `nml baseline` | B0: Muse Spark alone watches the video and lists near-misses |
| `nml export SPLIT` | Data for the replay viewer in `docs/` |
| `nml cost` | Spend so far, by model |

## Validation
- **Data:** the FLUID dataset (Scientific Data 2026, CC BY 4.0), with stabilised drone video of signalised intersections and reference trajectories from the authors' YOLOv8-OBB + SparseTrack pipeline. Results are reported as agreement with that reference, not as accuracy against ground truth.
- **Pre-registration:** splits, metrics and thresholds were fixed in [`validation/PREREG.md`](validation/PREREG.md) before any test or held-out run. Changes made afterwards are listed there with reasons. Splits:
  - development clip;
  - test clip;
  - a held-out intersection never used during development.
- **Results:**
  - [`validation/SELFTEST.md`](validation/SELFTEST.md) is regenerated by `nml selftest`;
  - [`validation/RESULTS.md`](validation/RESULTS.md) by `nml evaluate`;
  - the verifier and B0 results are in `validation/results/`.
- **Tests:** `uv run pytest` runs unit tests that use scripted fake models, so they cost nothing.

## Limits
- **Not crash predictions:** these are surrogate safety measures from minutes of video. A qualified traffic engineer must review any design.
- **CMF coverage:** the CMF Clearinghouse has no two-wheeler crash type, so two-wheeler conflicts are matched to the general crash type, and the memo says so.
- **Pedestrians:** pedestrian tracking from 120 m altitude is weak, so pedestrian results are descriptive.
- **3D view:** the 3D replay uses measured positions, lengths, widths and headings. Heights are schematic.

See [`LICENSES.md`](LICENSES.md) for data and model licences and [`PRIVACY.md`](PRIVACY.md) for how road users are handled.
