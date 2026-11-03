# Testing NearMissLens on new cases

This is for someone who did not build it and wants to see whether it holds up on inputs nobody chose for it.

## Install

```bash
git clone https://github.com/Morningstaaar36/nearmisslens && cd nearmisslens
uv sync                                  # Python 3.12
echo "MODEL_API_KEY=..." > .env          # a Meta Model API key; never commit it
set -a; . ./.env; set +a
uv run nml cities                        # which cities can be checked, and what each lacks
```

A Baseten key (`BASETEN_API_KEY`) is optional: with it, letters are drafted by Muse Spark Open; without it, by hosted
Muse Spark.

## Run a new case

Pick a city that `nml cities` lists as checkable, and give it something real:

```bash
uv run nml check "https://a-news-site.example/story-about-a-crash" --city CITY_ID           # a link: read first
uv run nml check "The mayor says this intersection had 40 crashes last year" --city CITY_ID # a claim: found by search
uv run nml check "PASTE THE STATEMENT'S TEXT" --as-source --city CITY_ID                    # the text is the source
uv run nml check "Drivers run the red light every morning" --kind report \
    --address "Street A & Street B" --photo "https://…/photo.jpg" --city CITY_ID           # a resident's report
```

In the registered runs a case cost $0.06 to $0.13 of Meta API (it is capped by `--budget`, default $0.50) and takes a few minutes, most of
it waiting for public map and data servers. The result is printed and saved as `runs/checks/<time>_<slug>/result.json`
and `report.md`.

The web app does the same: `uv run nml app`, open http://127.0.0.1:8770, choose "Check a claim yourself".

A city that is not in the registry, or has no crash data, gets a plain answer and no run. To add one:
`nml add-city ID --name NAME --bbox LAT_MIN LON_MIN LAT_MAX LON_MAX --agency AGENCY`, then
`nml discover LAT LON` (Muse Spark finds and validates the city's crash data).

## What the output means

| Field | Meaning |
|---|---|
| `status` | `published` (every gate passed), `abstained` (the desk could not get a case past the gates; `reason` says why), `unsupported_city`, or `error` |
| `corner` | the intersection the case is about (one per case) |
| `claims[].verdict` | `consistent with the record` (a number in the claim was tested against the record and matched), `differs from the record` (the record holds a different value for what the sentence names), or `cannot be checked against this record` (another area, period or kind of count). `frame` states the record's area, period and as-of date |
| `findings[]` | sentences, each citing the receipt (`D1`, `D2`, …) that holds its numbers |
| `sources[].quote_check` | `verified` (the quote is on the page), `unreadable` (the page could not be read here, so the quote is unverified). A quote not on its page is refused |
| `letter` | a drafted request to the agency that owns the road; every number in it was checked. Nothing is sent |
| `cost_usd.meta`, `seconds`, `asof` | what it cost, how long it took, and the date the records were read as of |

## What counts as a failure

Report any of these, with the `result.json`:

1. A published finding states a number the record does not hold, or attributes it to the wrong thing.
2. A quote is marked `verified` but is not on the page, or does not say what the finding uses it for.
3. A claim verdict is wrong: "consistent" for a number that was not tested, or "differs" when the source counts another
   area or period (that should be "cannot be checked").
4. The case is about a different intersection than the source names.
5. A licence plate, or a name the source did not print, appears anywhere.
6. A city outside the registry gets an answer instead of a refusal.

An `abstained` result is not a failure by itself: the desk is built to refuse what it cannot check. It is a failure if
the input was ordinary and checkable, and the reason shows the desk went wrong (for example, it read the wrong page).

## Rules for a fair test

- Do not change code or data between cases, and keep every result, published or not.
- Choose inputs before running any of them, and include some the desk should refuse.
- Note the commit you tested (`git rev-parse HEAD`); results differ between commits.
- Replay (`nml --replay ...`) reproduces saved runs only; new cases need live mode and a key.

## Before you commit: review a proposed project

For the engineer or directorate deciding whether to fund a project. Describe it as you would to a colleague:

```bash
uv run nml review "Leading pedestrian intervals at Street A & Street B, about \$15,000" --city CITY_ID
uv run nml review --example N          # a real proposal from validation/examples/proposals.json
```

What happens:
1. Muse Spark registers the proposal against the federal list of Proven Safety Countermeasures, then investigates the corner with the checked tools.
2. Code tests the proposal against the crash record and **sets the verdict**:
   - **proceed**;
   - **proceed only after a site check** (the estimate assumes something the public data cannot show);
   - **compare before committing** (another supported fix is expected to avoid at least twice as many injury crashes);
   - **not covered by the evidence** (no crash-modification study fits this fix at this site: the decision rests on a site study and an engineer's assessment);
   - **reconsider** (the record shows none of the crashes it targets, the fix is already installed, the city's own record contradicts it, or the stated cost is above the lifetime value of the harm it avoids);
   - **decide part by part** (a proposal with several parts, such as an interval and a turn phase, whose parts get different verdicts; each part's verdict is listed).

   A device built for another control than the map shows (a beacon where a signal is mapped within 80 m) is estimated as the proposal describes the site, with the control to be confirmed on site. A stated cost is compared with a fix's benefit only when it pays for that fix alone.
3. Muse Spark Open (Baseten) red-teams the decision. It is shown every value in the receipts and must rest each objection on one of them; code keeps an objection only if that fact is in the receipt, drops one that rests on the verdict itself, and lets the red team replace dropped ones once. Dropped objections are saved with the reason.
4. Muse Spark writes the memo, and the gate holds it to the code's verdict, the receipts' numbers and an answer to every kept objection.

The memo is printed and saved as `runs/reviews/<time>_<slug>/memo.md`, with `result.json` and `receipts.json` (the data behind every receipt id the memo cites). A review cost about $0.03 Meta plus $0.02 Muse Spark Open in development.

**The real proposals** in `validation/examples/proposals.json` come from agency plans, neighborhood commission resolutions, a community board letter, a petition and a news report. They are split by a fixed hash within each city:
- `registered`: run by the project as T26;
- `team`: tried by the team;
- `held_out`: never run by the project before review, so you can try proposals nobody tuned for.

`nml review --example N` runs row N; each row keeps its source link.

Each check also saves `receipts.json`: the data behind every receipt id a finding cites, so a number can be checked without rerunning.

**What counts as a failure here:** the memo is about a different corner than proposed; a part of the proposal is dropped; a number is not in the receipt it cites; an answer does not address its objection; or the verdict's reason is wrong given the receipts (for example "reconsider: no target crashes" where the record shows them). A town inside a city's bounding box (a suburb) must be refused, not reviewed against the city's records.

## A whole list: program review

For a directorate with a list of proposed projects (a capital program, a Safe Routes to School list, a council's requests):

```bash
uv run nml portfolio list.txt --city CITY_ID                       # one proposal per line
uv run nml portfolio list.csv --city CITY_ID --budget-total 500000  # a CSV with a "text" column and, optionally, "cost_usd"
uv run nml portfolio --example ID                                   # a real list from validation/examples/programs.json
```

Or start from the agency's own page:

```bash
uv run nml intake URL [URL ...] --city CITY_ID               # the projects on the page(s), checked; edit before reviewing
uv run nml portfolio --from-url URL [URL ...] --city CITY_ID  # read the page(s), then review and rank every project
```

Intake keeps a project only when its passage is on the page word for word and names both streets (a location list may rest on the list item plus the passage describing the work), keeps a cost only when the passage states it, and leaves out projects the page says are completed. A page that refuses automated readers is reported unreadable; save the page or paste its list into a file instead.

Each proposal is reviewed as above (three at a time). Then code, not a model, groups the list (build; build after a site check; compare first; decide part by part; not covered by the evidence; reconsider; not reviewed) and ranks each group by injury crashes avoided per dollar, then per year. With `--budget-total`, it lists the supported projects that fit, best value first, and the supported ones with no cost to rank. The program is saved as `runs/programs/<time>_<city>/program.md` and `program.json`, beside every proposal's review; an interrupted program resumes from that folder (`--out`) without paying twice. The web page takes 2 to 4 proposals at a time.

The real lists in `validation/examples/programs.json` come from the agencies' own pages, each project with the source's sentence: `registered` lists were run by the project as T29; the `held_out` list (DDOT notices of intent) was never run by the project before review.

**What counts as a failure in a program:** a proposal in the wrong group for its memo's verdict; a supported project missing from the total; a proposal reviewed at another corner; or a ranking that does not follow the numbers in the table.

