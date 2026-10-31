# NearMissLens

**A safety engineer for city streets that has to show its receipts.** Give it a city or a corner. It finds the worst corners, works out what their crashes have in common, checks what the city already tried, picks the fix the record supports and prices it, finds who has to act, and drafts the request. Every sentence it writes cites the receipt behind it, and a sentence whose numbers do not match its receipt is refused before anyone sees it.

**Open it:** [morningstaaar36.github.io/nearmisslens](https://morningstaaar36.github.io/nearmisslens/) has the case for each of New York's 304 Vision Zero priority intersections, with no key and no install.

![The copilot open on Bruckner Boulevard & Hunts Point Avenue: the city's priority corners on a map and a ranked list on the left; on the right the case, each sentence followed by the receipt it rests on](docs/img/copilot_bruckner.png)

## One corner, start to finish

`nml engineer nyc` screens New York's 304 priority intersections and opens the worst one: **Bruckner Boulevard & Hunts Point Avenue** in the Bronx. Its case, as the engineer wrote it:

- **The record.** 129 injury crashes in five years of police reports (29 pedestrians and 3 cyclists injured), the most of the 304. At the U.S. DOT's crash values, that is about $8.8 million a year. The last recorded safety work there is a 2015 street project.
- **What the crashes have in common.** 28% involved a truck or bus, against 16% at the city's other priority corners. 12% had "following too closely" recorded, against 6%. Both hold up after a correction for testing many patterns. Hunts Point is home to the city's food distribution market, and the crash record shows it.
- **What the city already tried.** New York's own leading pedestrian intervals cut pedestrian injury crashes 17% at 1,651 intersections, measured against intersections that got them later, and a fake earlier install date shows nothing. Its turn calming looks like −26% in a simple before/after, but crashes were already falling before the work, so the engineer does not credit it.
- **The fix and its price.** Longer yellow signal times: about 7 fewer crashes a year, worth $2.4 million a year (CMF 4215, the median of four studies that fit a signalized corner). Reflective signal backplates: 3.9 a year, $1.3 million (CMF 1410, the one FHWA cites).
- **Who must act.** Two owners. The New York State DOT, Region 11, owns the Bruckner Expressway (I-278), which runs overhead, and the Sheridan Boulevard (NY 895), according to the state's road inventory. The surface streets are not in that inventory, so they are the city DOT's. Council District 17 and Bronx Community Board 2 can push for the work.
- **The request.** A letter to both owners, copying the council member and the board, with each number checked against the record.

The first run takes about 40 seconds of public-data requests (median 36 s across the 304 corners). After that, a case rebuilds in under a second.

**Across all 304 corners**, the same run found:
- the city DOT is not the only road owner at 12 of them (the state DOT at 11, a toll authority at 1);
- 54 already got turn calming, the program whose drop the city's own record cannot separate from an earlier trend, so the engineer flags them before the same thing is proposed again;
- at 144, at least one crash pattern is more common than at the city's other priority corners. The owner split matters for anyone asking for a fix here: a letter only to the city DOT would miss the state agency that owns the expressway above the junction.

## How it works

The engineer is a Meta model with six tools. Each tool is plain code over public records with a check inside it, and each returns its data with a **receipt**: the datasets it read, the date the records run to, the checks it ran, and the seconds it took.

| Tool | What it reads | The check inside it |
|---|---|---|
| `screen_city` | The city's priority intersections and its police crash records | Each crash counted once where junction circles overlap |
| `root_cause` | Crashes within 100 m: who was hurt, vehicle types, recorded factors, time of day | A pattern is "over-represented" only if a one-sided binomial test against the city's priority corners passes after a Holm correction, with at least 10 crashes. The wording is "have in common", never "caused" |
| `test_programs` | Every program a registered study tested in this city, and the projects recorded at this corner | The causal gate (below). A corner that already got a program whose effect was not shown is flagged before it gets the same again |
| `choose_fixes` | FHWA Proven Safety Countermeasures and a curated set of 25 CMF Clearinghouse records | A crash-reduction factor applies only if it matches the corner's control and a crash group the record shows. The FHWA-cited record wins, else the median, never the largest |
| `who_must_act` | The state road inventory, council and community-board maps | No party without the dataset row behind it. An owner the inventory implies but does not list is marked "inferred" |
| `draft_request` | The facts above | Every number in the letter must be the record's value for the words next to it |

The agent finishes by calling `finish` with a summary and a list of claims, each citing a receipt. The **finish gate** refuses:
- a claim without a receipt;
- a number that is not the receipt's value for its label ("29 pedestrians were killed" when the record says 29 injured);
- a summary that says "caused", "failed" or "proves".

In our first agent run, Muse Spark Open's summary said a program had "failed". The record only says its effect was not shown, so that word is now refused, and the next run passed. That run took 7 turns and cost $0.07 on Baseten.

It runs two ways. `nml engineer "ADDRESS" --agent` lets Muse Spark Open choose the steps and write the claims. `nml engineer "ADDRESS"` runs the same tools in a fixed order, with claims written by code; that mode needs no model and builds the static site.

## Falsification-gated agents

The method is the gates. An agent can say what it likes, but a claim only reaches the reader after a deterministic test inside the tool has tried to break it with public data. This builds on Meta's verifiable-agent pattern from the Agents 102 workshop, which puts checks inside the tools so an agent cannot finish until its work passes them. It is close in spirit to POPPER (Huang et al., 2025), which has agents design falsification experiments for hypotheses. Meta's checks compare claims with documents. These gates check claims about the world: a number against the record, a crash-reduction factor against the site, a drawing against SAM 3.1, and "this fix works here" against the city's own history.

That last one is the **causal gate**. The statistics are standard road-safety evaluation: a comparison-group before/after (Hauer, 1997) with a placebo install date 19 months early. What is new here is that it sits inside the tool, so neither the engineer nor an AI analyst can tell a reader a program worked unless the city's own crash history agrees. [`docs/METHOD.md`](docs/METHOD.md) has the details. The rules for every test are in [`validation/BENCH_PREREG.md`](validation/BENCH_PREREG.md), and every result, including the failures, is in [`validation/BENCH.md`](validation/BENCH.md). Registration and results were often committed together, so git cannot confirm the order. Each new registration is now pushed on its own before it runs.

## What the gate found

![Each program's effect on pedestrian injury crashes as the causal gate measured it (dot and 95% interval, green when it passed) next to a simple before/after (orange ring)](docs/img/gates_forest.png)

| Program | Simple before/after | The causal gate |
|---|---|---|
| New York leading pedestrian intervals, 1,651 intersections | pedestrian injury crashes −24% | **Worked: −17%** (95% interval −22% to −11%); the placebo date shows no change. FHWA's cited figure is −13% |
| New York turn traffic calming, 227 sites | −26% | **Earlier trend:** in the 18 months before the work, crashes were already 22% below what the comparison predicted |
| Seattle leading pedestrian intervals, 371 intersections | −25% | **Worked: −33%** (−52% to −13%), the same design run unchanged in a second city; both placebos show no change (pedestrian outcome) |
| Washington DC leading pedestrian intervals, 267 intersections | −31% | **Inconclusive: −19%** (−35% to +1%); 600 of DC's sites had no later-treated comparison |
| New York speed humps (1,008 sites) and San Francisco continental crosswalks (780) | | **No measurable change** (−0.4% and +4%) |
| New York enhanced crossings and San Francisco painted safety zones | | **Not shown:** fewer than 100 usable sites each |
| 200 fake programs (random sites and dates, nothing installed) | credits 8.0% | credits 5.5% (3.1–9.6%), above the 2.5% it nominally allows |

**An AI analyst with and without the gate.** We gave Muse Spark Open the programs blind and let it write and run its own analysis code in a sandbox. On its own, it missed New York's leading pedestrian intervals, credited turn calming (−9%) and speed humps (−11%), called DC's intervals an "increase" while reporting −15%, and credited 2 of 20 fake programs. With the gate deciding on held-out sites, it confirmed New York (−16%) and Seattle and refused the rest. It also passed 5 of 20 fake programs, all with short designs it chose itself.

**We tested the tester.** Those 5 false passes led to a stricter, calibrated gate, which also requires a program to beat 97.5% of 200 fake programs run through the same design. On 100 fresh fake programs it cut false passes from 6 to 3 (and from 3 to 2 with the short design). But it no longer confirms the leading pedestrian intervals: New York's effect is stronger than 87% of fake programs, not 97.5%. We kept the original gate, and the copilot shows that rank next to the verdict. Read the interval result as consistent evidence across two cities and published studies, not as proof.

Projection, not a test: 119 of the 304 priority corners have no leading pedestrian interval. At New York's measured effect, adding them would prevent about 43 pedestrian injury crashes a year (29–56). Each site still needs an engineer's check.

## Try it

```bash
uv sync                                                    # Python 3.12; no extras needed
uv run nml --replay engineer "Bruckner Boulevard & Hunts Point Avenue, Bronx, NY"
uv run nml --replay engineer nyc                           # screen the city, open its worst corner
uv run nml app                                             # the copilot on http://127.0.0.1:8770
uv run nml pages                                           # rebuild the static site in docs/
uv run nml treatments T11                                  # rerun New York's study and its gate
uv run nml --replay selftest                               # offline self-test; the drone-video rows need nml fetch
```

`--replay` reads public records as of the pinned date in `validation/ASOF` and serves model calls from the cache, so the commands above give the same answers without keys or network once the replay cache (`nearmisslens_replay_cache.tar.gz` on the GitHub release) is unpacked. Keys for live runs go in `.env`: `BASETEN_API_KEY` (Muse Spark Open), `MODEL_API_KEY` (Meta Model API), and optionally `MAPILLARY_CLIENT_TOKEN`. Every paid call is cached and logged, and `NML_BUDGET_USD` caps Meta spend.

**Cities are data, not code.** Each dataset, district map, road inventory and agency is an entry in [`registry.json`](nearmisslens/data/registry.json), and each study is a JSON file in [`validation/studies/`](validation/studies/). The data agent (`nml discover LAT LON`) finds a new city's crash data in the public Socrata and ArcGIS catalogs; its validator refused two wrong mappings for Seattle before accepting one. The program agent (`nml programs seattle`) found Seattle's leading pedestrian interval layer, turned down 39 other layers, and `nml gate seattle` then measured −33% on 366 intersections, matching the hand-built study.

## Meta models

| Model | Where | What it does |
|---|---|---|
| **Muse Spark Open** on Baseten | the engineer, the analyst, letters | Chooses the engineer's steps and writes its claims; writes and runs analysis code in a sandbox; drafts the request letters. All three go through gates |
| Muse Spark | data agent, program agent | Maps a new city's datasets; a validator in the tool refuses bad mappings |
| SAM 3.1 | drone video, drawing check | Tracks vehicles (recall 0.51–0.97 on unseen flights) and two-wheelers (0.00–0.73) in drone video; pedestrians are not tracked from 120 m. Checks that a drawn fix is really there and no real car moved |
| Muse Image | fix drawings | Draws the top fix on the aerial photo; 13 of 20 drawings pass the SAM 3.1 check |

**Near-misses from video**, where video exists: SAM 3.1 tracks road users in drone footage, and the conflict engine measures time-to-collision and post-encroachment time (FHWA SSAM definitions). On 11 unseen one-minute windows, better kinematics and re-seeding raised PET ≤ 1.5 s F1 from 0.23 to 0.36, though neither step met its registered rule. The drone viewer is at [`docs/video/`](docs/video/).

## Tried, and did not help

| What | Result |
|---|---|
| Muse Wonder planning which video to review | Covered 32.7 reference conflicts per dollar against 106.3 for a greedy rule |
| A Muse Spark / Muse Wonder review panel (proposer, skeptic, arbiter) | Did not change the audit facts; its ablation had a bug that is now fixed but was not rerun |
| Muse Spark scouting points for SAM | Missed the registered go/no-go rule |
| Muse Spark watching video clips to rate conflicts | Precision rose from 0.46 to 0.69 at equal recall, but removing the video raised F1 (0.106 to 0.198) |
| Residents' near-miss reports in crash prediction (DC) | No gain on held-out areas and future years (top-5% precision 0.586 with and without) |
| Muse Spark Open as the complaint checker | 25 of 32 self-made complaints; Muse Spark got 32 and a fixed rule 28 |

The number checker itself: without it, 4 of 34 memos used a number not in the record. With it, none do, because it refuses them.

## Limits

- **A screening aid, not a design.** Estimates use the Highway Safety Manual's simple method, so fixes must not be added together, and a qualified engineer must review every recommendation.
- **The causal gate is observational.** Cities choose their sites, so some regression to the mean can remain even with the placebo, and 5.5% of fake programs passed it.
- **Police factors are an officer's account.** "Have in common" is a pattern in the record, not a cause. A third of the crashes here have no factor recorded, and the page says so.
- **"No recorded treatment" means none in the city's open datasets** within 60–150 m. Work recorded elsewhere is not seen.
- **Road owners come from the state inventory**, which lists state and designated routes; a street it does not list is shown as an inferred city street.
- **US cities only so far.** New York, Seattle, Washington DC and San Francisco are registered. A city elsewhere needs its crash data, a harm table and an owner layer in the registry.

## Built during the hackathon

Meta Global AI Developer Hackathon, Indie track, "Push the Frontier". Solo entry by Morningstaaar36.

Every line here was written during the event (Oct 27 – Nov 4, 2026). The first commit, `dc089bf`, is dated Oct 27 (ET), and no earlier code was used. Built in that window: the engineer and its six tools, the finish gate and receipts, the causal gate and its studies, the root-cause and road-owner tools, the CMF eligibility rules, the copilot page and static site, the drone-video pipeline and the benchmark. Data and model licences are in [`LICENSES.md`](LICENSES.md), and what is stored about whom is in [`PRIVACY.md`](PRIVACY.md).
