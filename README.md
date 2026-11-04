# NearMissLens

**Check a street-safety project against the city's own crash record before the money is spent.**

[**Use it live**](https://hussainshahraz720--nearmisslens-copilot-web.us-east.modal.run) (no account, key or install) ·
[Saved results](https://morningstaaar36.github.io/nearmisslens/) · [Test it yourself](TESTING.md) ·
[The evidence in full](EVIDENCE.md)

![The start screen: four tasks, each in the colour of a road-sign family, with how long each usually takes](docs/img/start.png)

A traffic engineer or an agency describes what it plans to build. NearMissLens looks up the corner's police crash
records, the city's own past safety programs, the federal studies behind each fix and the owner of each road, and
returns a memo with a verdict and its sources. **Meta's models do the research; code sets the verdict**, and nothing
is shown until code has checked every number against the record and every quote against its page.

## What you can do with it

| Task | You give it | You get back | Usually |
|---|---|---|---|
| **Review a project** | one fix at one intersection, with its cost if known | a verdict (proceed, proceed after a site check, compare first, not covered by the evidence, reconsider), its reasons, and a pre-mortem written by a second model | about a minute |
| **Review a list** | several proposals, or an agency's web page that lists them | each one reviewed, then ranked by code by what the evidence supports, within your budget | a few minutes |
| **Check a claim** | a news link or an official's statement about a corner | which numbers hold, which differ, and which the record cannot test, with every quote checked on its page | about 8 minutes |
| **Look up a corner** | an intersection | what its crashes have in common, what the city already tried, which fix the record supports, who must act, and a drafted request letter | at once for saved corners |

It covers **New York, Washington DC, Chicago, Seattle and San Francisco**, the cities that publish geocoded crash
records. Cities are data, not code: each is an entry in [`registry.json`](nearmisslens/data/registry.json).

![A saved memo: a neighborhood commission asked for a leading pedestrian interval at 22nd St & L St NW in Washington. Code says "reconsider" because DC's own signal records show one is already installed; each finding cites its receipt, and the red team's objections are answered](docs/img/review_memo.png)

## Results at a glance

Every test was registered before it ran ([`validation/BENCH_PREREG.md`](validation/BENCH_PREREG.md)); failures are
reported next to successes. The full story, with what each review of the results still found wrong, is in
[EVIDENCE.md](EVIDENCE.md).

| What was tested | Result | Rule |
|---|---|---|
| The desk on 36 fresh real cases from the live web (T21c–T21e) | 33 published; **72 of 72** quotes found on the page they cite; $0.063–$0.126 a case | met |
| Muse Spark alone, same inputs, same web search (T24) | **26 of 73** of its quotes from readable pages are not on those pages | baseline |
| `nml check` on 12 inputs nobody chose (T25) | 10 of 10 real inputs published, 26 of 26 quotes verified, both controls caught | met |
| Review a project: 7 real proposals from 5 cities' plans (T26–T28) | 7 of 7 memos, all on the proposed corner; **32 objections** survived the fact check (13 before the rework) | met |
| Review a list: 3 real agency programs (T29b) | 21 of 23 reviewed, each on its own corner; the ranking rebuilt exactly; $0.079 a proposal | met |
| Read an agency's web page into projects (T30c) | **16 of 16** hand-collected projects found, 55 kept; $0.063 a page | met |
| The causal gate on New York's leading pedestrian intervals (T11) | **−17%** pedestrian injury crashes (95% interval −22% to −11%); a naive before/after says −24% | passed |
| A corner's own crash count against an independent count (T31b) | agrees at 3 of 10 corners; mean error 4.7 crashes against the 100 m circle's 22.9 | **not met** |
| A frozen patch against a held-out attacker (T18) | cut accepted false claims by 46%, short of the 50% registered | **not met** |

Independent testers saw only [TESTING.md](TESTING.md); their reports are kept as written in
[`validation/independent/`](validation/independent/), with what we changed after each.

## How it works

```
your input ──▶ Muse Spark 1.3 (Meta Model API) works the case with checked tools
                 ├─ web_search, read_page        find and read the source        ─▶ quote must be on the page
                 ├─ tool search over the registry the city's open datasets
                 ├─ investigate                   crash records, past programs,   ─▶ receipts R1, R2, …
                 │                                federal crash-reduction studies,
                 │                                road owners
                 └─ check_claim                   a number against its receipt
             ──▶ code sets the verdict (never the model)
             ──▶ Muse Spark Open (Baseten) argues against it ─▶ code keeps an objection only if its fact checks out
             ──▶ the memo must answer every kept objection   ─▶ finish gate: numbers, quotes, wording
```

| Model | Its job | What checks it |
|---|---|---|
| **Muse Spark 1.3** | runs the desk: searches, reads, investigates, writes the memo; reads agency pages into project lists | the finish gate: every number against its receipt, every quote against its page |
| **Muse Spark Open** (Baseten) | the red team's pre-mortem; request letters; answers about a corner | each objection must name a receipt field and value; every number in a letter is checked |
| **Muse Voice Transcribe** | a spoken proposal from the site (`nml review --audio`) | the transcript goes through the same review |
| **SAM 3.1** | counts people and cars in Seattle's traffic-camera frames (Corner Watch) | agreement between image and video modes |

The causal gate decides whether a city program reduced crashes. It is a comparison-group before/after with a
placebo date, and neither the model nor an engineer can override it. It is described in [EVIDENCE.md](EVIDENCE.md#the-causal-gate)
and [`docs/METHOD.md`](docs/METHOD.md).

## Run it yourself

```bash
uv sync                                                        # Python 3.12
uv run nml --replay engineer "Bruckner Boulevard & Hunts Point Avenue, Bronx, NY"   # no key: a corner's case
uv run nml --replay plan nyc                                   # no key: a city's action plan
uv run nml app                                                 # the page on http://127.0.0.1:8770
uv run nml review "Leading pedestrian intervals at Street A & Street B, about \$15,000" --city CITY   # needs MODEL_API_KEY
uv run nml portfolio --from-url URL --city CITY --budget-total 500000                              # a whole program
uv run pytest -q                                               # the test suite, no network or keys
```

Keys go in `.env` (`MODEL_API_KEY` for the Meta Model API, `BASETEN_API_KEY` for Muse Spark Open). Every paid call is
cached and logged; `--replay` serves the cached answers with records pinned to `validation/ASOF`.
[TESTING.md](TESTING.md) walks a tester through each task and what counts as a failure.

## Running it for others

The live page runs on Modal (`nearmisslens/modal_web.py`) as one small container that scales to zero when idle:
- a **daily model budget** shared by every visitor (the page shows what is left), and a request cap for new corners;
- a **per-visitor limit** of 10 paid jobs an hour, kept as a salted hash in memory only, never written;
- `GET /health` for an uptime monitor, security headers, and CORS only for the GitHub Pages copy;
- no account, cookies, analytics or request log ([PRIVACY.md](PRIVACY.md));
- a beta notice on every page: it is a screening aid, not engineering advice.

`modal deploy nearmisslens/modal_web.py` deploys it after `modal secret create nearmisslens-keys MODEL_API_KEY=… BASETEN_API_KEY=…`.

## Where things are

| Path | What it holds |
|---|---|
| `nearmisslens/review.py`, `portfolio.py`, `intake.py`, `check.py` | the four tasks: review a project, review a list, read an agency page, check a claim |
| `nearmisslens/orchestrator.py`, `agent.py`, `meta_client.py` | the desk: Muse Spark's tool loop, the finish gate and the Meta API client |
| `nearmisslens/engineer.py`, `brief.py`, `opendata.py`, `context.py`, `rootcause.py`, `jurisdiction.py`, `harm.py` | the checked tools: geocoding, crash records, patterns, fixes, road owners, costs |
| `nearmisslens/treatments.py`, `falsify.py` | the causal gate |
| `nearmisslens/app.py`, `budget.py`, `jobs.py`, `modal_web.py`, `web/` | the server, its limits and the page |
| `nearmisslens/data/registry.json`, `fhwa_psc.json` | cities as data; the federal fixes and the limits of each study |
| `validation/` | registered rules, results, independent reports, the proposals test set |
| `tests/` | the test suite, including ones that tie every number above to its result file and fail on any place name in the generic code |
| other modules | research that did not make the product (drone-video tracking, aerial-photo reading, mechanism mining); kept because [BENCH.md](validation/BENCH.md) reports them |

## Limits

- **A screening aid, not a design.** Estimates use the Highway Safety Manual's simple method, one fix at a time, and a
  qualified engineer must review each one.
- **The gates check numbers, quotes and wording, not whether a finding is the right one to make.** An independent audit of 12 published desk
  cases found an error in 7; the causes are fixed, and no person has audited the cases yet.
- **Whose crashes a corner's counts are** depends on rules the open data does not settle (T31b, not met).
- **The crash record lags the news** by days to weeks; every answer states the date its records run to.
- **US cities only so far**: the method needs geocoded crash records, which most countries do not publish.

All the limits are in [EVIDENCE.md](EVIDENCE.md#limits).

## Built during the hackathon

Meta Global AI Developer Hackathon, Indie track, "Push the Frontier". Solo entry by Morningstaaar36. Every line was
written during the event (Oct 27 – Nov 4, 2026); the first commit, `dc089bf`, is dated Oct 27 (ET). Data and model
licences are in [LICENSES.md](LICENSES.md); what is stored about whom is in [PRIVACY.md](PRIVACY.md).
