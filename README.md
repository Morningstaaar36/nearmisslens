# NearMissLens: a junction safety copilot

**Cities act on crash reports, after people are hurt. NearMissLens tells a city engineer which intersections need fixing, what to fix, how much it should help, and what the city has already done. It works from open records, and from near-misses measured in video where video exists. Every claim is checked against the data.**

The problem in numbers:
- New York's 304 Vision Zero priority intersections had **11,981 injury crashes and 60 deaths in five years**.
- **225 of them (74%)** had at least 10 injury crashes in that time and no recorded safety treatment within reach. That means no Street Improvement Project, Leading Pedestrian Interval, turn calming or signal retiming in the city's open datasets ([`T9`](validation/BENCH.md)).
- The copilot screens a junction in about a minute, at under a cent of model cost.

Built during the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026). Every line of code in this repository was written during the hackathon.

## What it does
`nml brief "Delancey Street & Essex Street, Manhattan, NY"`, or click a junction in the web app (`nml app`):

1. **Official record.** Police-reported crashes within 100 m over five years: who was hurt, factors, crash types, darkness and wet roads where recorded. Also the city's designations (High Injury Network, Vision Zero priority) and its recorded projects and treatments.
2. **Ranked, cited fixes.** Every FHWA Proven Safety Countermeasure whose CMF Clearinghouse record targets a crash group in the record, ranked by **expected crashes avoided per year**, using the Highway Safety Manual's simple method (crashes per year × (1 − CMF)).
   - Fixes whose precondition the record does not show are flagged "verify on site".
   - Fixes that only work at night or on wet roads count only that share of crashes.
3. **The street.** The city's own aerial photo, or USGS national imagery anywhere in the US, plus a Mapillary street-level photo. Muse Image draws the top fix on the aerial, and SAM 3.1 checks that the drawing added it.
4. **A checked brief.** Code builds the ranking; a Muse Spark agent writes the narrative. A checker rejects any number that is not in the record, and the agent must fix it.
5. **Near-misses from video**, where video exists. SAM 3.1 tracks every road user in drone video, and the conflict engine measures TTC and PET (FHWA SSAM definitions) and ranks near-miss hotspots. That gives evidence before crashes happen. On unseen footage it now matches about 1.5 times as many of the reference conflicts as at the start (below).

**Any city, not four.** City data is not code. Each dataset is an adapter in [`nearmisslens/data/registry.json`](nearmisslens/data/registry.json). For a city it has never seen, the **data agent** (`nml discover LAT LON`):
- searches the public Socrata and ArcGIS catalogs;
- has a model map the fields to one schema;
- accepts the mapping only if it passes checks on real records (records near the point, dates that parse and are recent, numeric injury fields). The checker sits inside the agent's tool, so the model fixes its own errors.

On Seattle, which had no hand-written support, it rejected the vehicle-level and person-level tables, fixed its own mapping after two validator refusals, and produced a working adapter (37,856 records within 400 m of the test point), for $0.03.

## The agents and the Meta models
| Agent | Model | Job |
|---|---|---|
| Brief writer, context memos | Muse Spark Contributor, **Muse Spark Open** (Baseten) or **Muse Glimmer** (Modal GPU, `nearmisslens/glimmer_modal.py`) | Narrative of the record, every number checked |
| Data agent | Muse Spark Open (Baseten) | Finds and maps any city's open crash data; validator inside its tool |
| Tracker | SAM 3.1 video + image | Zero-shot tracking of every road user; re-seeding of missed scooters from single-frame detections |
| Engineer | Muse Image + SAM 3.1 | Draws the fix on the real aerial photo, checked by SAM |
| Intake | Muse Voice Transcribe + Muse Spark | Checks a resident's complaint against the evidence; refuses when it is not supported |
| Review panel and manager | Muse Spark, Muse Wonder | Proposer/Skeptic/Judge on countermeasures; end-to-end review with human sign-off |

## Does it work? (NML-Bench, pre-registered in [`validation/BENCH_PREREG.md`](validation/BENCH_PREREG.md))
Positive, mixed and negative results are reported as they came out. Full tables are in [`validation/BENCH.md`](validation/BENCH.md).

| Question | Result |
|---|---|
| Does the city's record say a junction needs work? (T9, all 304 NYC priority intersections) | 225 (74%) have ≥ 10 injury crashes in 5 years and no recorded treatment; 88 have none on record at all. The first run, with street projects only, found 267; we widened the definition before claiming, and both are reported. |
| Does the data agent generalise? | Seattle (no prior support): correct dataset found, mapping fixed by its own validator, adapter validated on real records. The same validator also found two errors in our hand-written DC adapter. |
| Does near-miss detection from video work on unseen footage? (11 one-minute windows: 2 new days and a never-seen junction, 241 reference conflicts) | Better kinematics plus re-seeding raised TTC F1 from 0.110 to 0.199 (95% interval for the re-seeding gain +0.03 to +0.13) and PET ≤ 1.5 s F1 from 0.23 to 0.36. Recall rose from 0.19 to 0.29. The pre-registered PET rule for re-seeding was narrowly not met (interval −0.02 to +0.12). |
| Do hotspots persist across days? (all 14 FLUID flights) | Yes: Kendall tau 0.47 over 26 different-day pairs, permutation p = 0.001. |
| Does the targeted fix beat chance? | Removing red-light entrants removes 1.57× as many conflicts as removing the same number of random road users. This is an upper bound on conflicts, not crashes avoided. |
| Do residents' near-miss reports improve crash prediction? (T10, Washington DC, held-out 30% of the city, future years) | **No.** Fusing 5,593 resident reports with crash history in an Empirical Bayes model did not beat crash history alone (top-5% site precision 0.586 vs 0.586; interval −0.03 to +0.02), even at sites with little crash history. Complaint maps should not drive budgets on their own; measured near-misses are the next test. |
| Are complaints checked correctly? (32 complaints) | Muse Spark agent 100% at $0.0016 each; Muse Wonder 96.9% at $0.098; Muse Glimmer (open weights, one Modal L4 GPU) 87.5%; fixed rule 87.5%; Muse Spark Open (Baseten) 78%. No answer from any agent carried an ungrounded claim. |
| Does the checker matter? | City memos: 0 of 34 ungrounded with it vs 4 of 34 without. With the checker, memos written on Spark Open and on Glimmer also had 0 of 34. The review panel produced no ungrounded claims either way. |
| Is a bare model enough? | Muse Spark watching the video alone: event F1 0.02, against 0.32 for the pipeline. |
| Does it scale to real briefs? | The 20 NYC plan-gap intersections with the most injury crashes all got a checked brief (memo on Muse Spark Open). 13 of their 20 fix drawings pass the SAM 3.1 check, with real road users protected. |

Agreement for video is with FLUID's reference trajectories (a trained YOLOv8-OBB + SparseTrack pipeline), not ground truth.

Negative results:
- the Scout (Spark pointing for SAM) lowered precision;
- giving the verifier the video hurt it;
- the Wonder budget conductor beat a simple motion heuristic only on pedestrian and two-wheeler conflicts;
- Muse Spark Open as a conflict verifier on unseen footage kept too few candidates (F1 0.46 to 0.08), so it is not used.

## Demo
The 2:09 demo video (attached to the GitHub release, with a 20 s cut) is made by `nml demo --copilot`. It records the real app, intake page and viewer, with narration by a local open-source voice (Kokoro, Apache-2.0). Every spoken number is read from `validation/`.

## Quick start
```bash
uv sync                                    # Python 3.12
uv run nml brief "Atlantic Avenue & Flatbush Avenue, Brooklyn, NY"   # needs BASETEN_API_KEY or MODEL_API_KEY for the memo
uv run nml app                             # web app on http://127.0.0.1:8770 (map, citywide layer, briefs)
uv run nml discover 47.6097 -122.3331      # data agent: add a city to the registry
uv run nml citywide                        # plan-gap screen of every NYC priority intersection
uv run nml fetch && uv run nml --replay selftest   # the video pipeline's self-test, offline
uv run nml bench                           # rewrite validation/BENCH.md from stored results
```
Keys go in `.env`:
- `MODEL_API_KEY` for the Meta Model API;
- `BASETEN_API_KEY` for Muse Spark Open;
- optionally `MAPILLARY_CLIENT_TOKEN`.

Every paid call is cached and logged; `NML_BUDGET_USD` caps Meta spend; `--replay` never calls an API.

To rerun everything without keys or spend, download `nearmisslens_replay_cache.tar.gz` from the GitHub release and unpack it in the repo root (`tar -xzf nearmisslens_replay_cache.tar.gz`). It holds every cached model and API response, the briefs, the audits and the cost ledgers.

## Limits
- **A screening aid, not a design.** Estimates use the Highway Safety Manual's simple method, not Empirical Bayes, and fixes must not be added together. Where a city does not record crash type, the angle and turning estimate is an upper bound. A qualified engineer must review every recommendation.
- **"No recorded treatment" means none in the city's open datasets** within 60–150 m. Work recorded elsewhere is not seen.
- **Video agreement is partial.** About 3 in 10 reference conflicts are found on unseen footage. Pedestrians are not tracked from 120 m drone altitude.
- **Crash and plan data need an open-data portal.** The data agent finds them where they exist; elsewhere the brief uses OpenStreetMap and says so.

See [`LICENSES.md`](LICENSES.md) for data and model licences (FLUID CC BY 4.0, Mapillary CC BY-SA, US public-domain imagery, city open data terms) and [`PRIVACY.md`](PRIVACY.md).
