# Changelog

## 1.0.0 (November 4, 2026)

The first release meant for use by people outside the project: a public live site, a static copy on GitHub Pages,
and a command-line tool, each with its tests and its limits written down.

**For people using it**
- Four tasks: review a project, review a list (or an agency's web page), check a claim, look up a corner.
- **Find on the web:** pick a city and Muse Spark searches the web for the agency's own pages of planned intersection
  projects; code opens each page, keeps it only when the passage is on it word for word, and reads its projects into
  the form to tick and review. A corner can also search for what has been published about it. `nml find CITY`.
- Each task reads like a flow chart:
  - the start screen draws who does what (you, Muse Spark, code, Muse Spark Open);
  - each task shows three steps that advance as the job runs;
  - results lead with a road-sign verdict and charts, with the detail folded away.
- **Charts:**
  - a corner's numbers at a glance, and who was hurt;
  - its fixes on one scale, against the crashes each targets;
  - a review's parts against the best alternative;
  - a list ranked in its verdicts' sign colours;
  - a claim check as a tally.
- **Real cases run live** (Saved results): NYC DOT's Lafayette Street intervals, a Seattle signal and a Chicago
  all-way stop, each checked by hand against the city's own data.
- **Nothing blocks:**
  - map tiles come from Esri's street map, with OpenStreetMap's as the fallback;
  - a lookup falls back to Photon when Nominatim refuses;
  - Overpass falls back to its mirrors, then to the OSM API.

**For people running it**
- `GET /health`, a daily model budget shared by all visitors (the page shows what is left), and a limit of 10 paid
  jobs an hour per visitor (a salted hash in memory only).
- Security headers. CORS is allowed only for the Pages copy.
- Job status without races: atomic writes, and a job's liveness is read before its file.
- CI passes on a fresh clone with no keys, data or extras installed.

**Fixed after the live cases**
- Request letters were refused whenever they named a fix whose estimate needs a site check ("better street
  lighting" read as claiming the corner has none). Both the Seattle and Chicago letters failed this way.

**Counting**
- A corner's crashes are its own:
  - crashes the city places at another intersection, on another street or mid-block are left out;
  - a crash the data does not place at a named intersection counts only within 30 m of the junction (T32).
- New York's deaths include the dataset's total. A 2023 death recorded with every mode at zero was missing from the
  case and the letter.
- Saved reports in all four cities were rebuilt this way. The plans' totals fell sharply (New York's largest
  estimates add up to 136 crashes a year, not 338), because the 100 m circle had counted neighbouring corners'
  crashes.

**Registered tests in this release**
- T28 to T30c met.
- T31, T31b and T32 not met. T32: 7 of 10 corners agree with an independent count, up from 3; mean error 3.9 crashes
  against the circle's 40.5.

Every result, met or not, is in `validation/BENCH_PREREG.md` and `validation/BENCH.md`.

## 0.x (October 27 – November 3, 2026)

Built during the Meta hackathon:
- the desk (T21 to T21e);
- the causal gate (T11 to T14b);
- the red team (T18 to T20b);
- "Before you commit" (T26 and T27);
- the drone-video pipeline that came before it (T1 to T10, not part of the product).

The full history is in git and in `EVIDENCE.md`.
