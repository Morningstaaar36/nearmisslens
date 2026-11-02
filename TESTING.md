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
