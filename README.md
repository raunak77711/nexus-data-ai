# AI Data Worlds

Upload a CSV. The app works out what the data *is*, decides which kind of
interactive world fits it, builds that world — and shows you the code behind
every chart it drew.

## The USP

**AI builds the app — and you can still see how it works.**

Most "AI builds your dashboard" tools are black boxes. You get a chart, you have
no idea what it did to your data, and you cannot check it or take it with you.
This one opens every chart up. Under each figure is a "Show the code" panel
containing real, runnable pandas and plotly that reproduces that exact figure if
pasted into a notebook with `df` loaded.

That claim is stronger than it usually is, because of how it is implemented. The
code is not a description written alongside the plotting logic — those two drift
apart the first time someone changes one and forgets the other, and a glass box
that lies is worse than no glass box at all. Instead the relationship is
inverted: the code string is rendered first, then **executed**, and the figure
you see is whatever that snippet produced. There is only one artefact, so
divergence is impossible rather than merely unlikely.

`scripts/test_worlds.py` proves it: it re-executes every snippet in a fresh
namespace containing only `df` and asserts the replayed figure's plotly JSON is
byte-identical to the one the app shipped.

## Architecture

```
                          ┌──────────────────────┐
   your.csv ─────────────▶│  app.py (Streamlit)  │   renders only, decides nothing
                          └──────────┬───────────┘
                                     │  DataFrame
                                     ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  core/         framework-agnostic — never imports streamlit      │
   │                                                                 │
   │   profiler.py ──▶ profile dict {columns, semantic types, flags}  │
   │        │                                                        │
   │        ▼                                                        │
   │   router.py ────▶ routing dict {archetype, target/time/entity}   │
   │        │            │                                           │
   │        │            ├── Gemini (google-genai)   source="llm"     │
   │        │            └── rule-based fallback     source="fallback"│
   │        ▼                                                        │
   │   worlds/                          ml.py                        │
   │    ├── timeseries.py               forecast() + naive baseline   │
   │    ├── geo.py                                                   │
   │    ├── tabular.py                                               │
   │    └── _glassbox.py  ◀── renders code, execs it, returns the fig │
   └─────────────────────────────────┬───────────────────────────────┘
                                     │  {figures, stats, code, warnings, status}
                                     ▼
                          ┌──────────────────────┐
                          │  charts + "Show the  │
                          │  code" expanders     │
                          └──────────────────────┘
```

Nothing in `core/` imports Streamlit. Every module takes plain inputs
(DataFrames, dicts, scalars) and returns plain outputs (dicts, DataFrames,
plotly Figures, strings), so the same code can be served from FastAPI without
modification. The test for whether logic belongs in `app.py` is simple: would it
still be true if the UI were a REST endpoint? If yes, it belongs in `core/`.

## How it works — the four stages

### 1. Profile (`core/profiler.py`)

Every column is assigned exactly one *semantic* type — what it means, not what
dtype pandas gave it: `datetime`, `numeric`, `categorical`, `geo_lat`,
`geo_lon`, `text`. The result is a compact, JSON-safe dict that every later
stage consumes.

### 2. Route (`core/router.py`)

The profile summary — never the rows — is sent to Gemini, which picks one of
three archetypes (`timeseries`, `geo`, `tabular`) and the columns that world
needs. The answer is validated against the profile before use, so a hallucinated
column name degrades to the rule-based pick rather than crashing a chart three
layers down. If the API is unavailable, the key is missing, or the response
fails validation, deterministic rules take over and the result is marked
`source="fallback"`. The app always tells you which path ran.

### 3. Build a world (`core/worlds/`)

| Archetype | Figures |
|---|---|
| `timeseries` | resampled line chart with rolling-mean overlay; split by category (top 6 by volume) |
| `geo` | scatter map on OpenStreetMap tiles, points coloured *and* sized by the measure, view fitted to the data's bounding box |
| `tabular` | distribution histogram with mean line; mean-by-category bars (top 15); correlation heatmap |

Every world returns the same shape — `figures`, `stats`, `code`, `warnings`,
`status` — so the presentation layer renders any archetype through one code
path.

### 4. Forecast (`core/ml.py`)

For timeseries only, on request: a `RandomForestRegressor` over `lag_1`,
`lag_7`, `rolling_mean_7`, `day_of_week` and `month`, scored on a chronological
last-20% split, always reported next to a naive "tomorrow looks like today"
baseline.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

cp .env.example .env           # then paste your key into it
python scripts/make_samples.py # generates samples/
```

The key comes from [Google AI Studio](https://aistudio.google.com/apikey) and
goes in `.env` as `GOOGLE_API_KEY`. `.env` is gitignored.

**The app runs without a key.** Routing falls back to the built-in rules and the
badge turns amber. Everything else — the worlds, the code panels, the forecast —
works identically.

## Run

```bash
streamlit run app.py
```

Then upload one of the files from `samples/`.

## The detection heuristics, and why they are what they are

The profiler's rules are deliberately conservative. A wrong semantic type
silently produces a wrong world, which is worse than an honest `text`.

**Datetime — ≥80% of a 500-row sample must parse into a plausible year.**
Requiring 100% would reject an obviously temporal column over three dirty cells
("N/A", a header repeated mid-file); accepting any parse at all would flag free
text, because pandas happily reads a date out of a sentence containing "May".
The 1900–2100 window exists because the parse rate alone is not enough — testing
found an ID column of the form `ST0004` parsing at 100%, since dateutil reads it
as the year 4 AD. Numeric columns are skipped entirely: `pd.to_datetime` turns
the integer `2020` into an epoch offset, so every numeric column would parse.

**Geo — a recognised name AND a plausible coordinate range.** Name alone
false-positives on `latency` and `long_description`. Range alone flags every
small number in the file — percentages, ratings, deltas. The sample data
includes a `latency` column specifically to catch this, and the test asserts it
does not become `geo_lat`. A lone latitude is not enough: `has_geo` requires a
matched pair, because you cannot map half a coordinate.

**Categorical — at most 20 distinct values, plus a repetition ratio on files of
200+ rows.** The absolute cap alone would call a 20-row table's primary key a
category; the ratio alone would call a 10,000-value ID column in a 10-million-row
table one. The ratio is gated on row count because `n_unique/n_rows < 0.05` is a
claim about *repetition*, and repetition is only measurable once there are enough
rows to repeat — on a 100-row file it permitted at most 4 distinct values, so an
ordinary 6-region column came back as `text` and every category chart silently
vanished. Applied to numeric columns too, deliberately: 8 distinct integers
across 5,000 rows is a category code (a region id, a star rating), and taking its
mean would be meaningless.

**Precedence: datetime → geo → categorical → numeric → text.** The order encodes
strength of evidence. A successful date parse, or a name-and-range coordinate
match, is hard evidence about what a column *means*. Cardinality is only a
statistical hint. Numeric and text are what is left when nothing more specific
fits.

### Two more decisions worth naming

**The trend direction comes from a least-squares slope, not first-vs-last.**
Comparing endpoints asks two of the n points to speak for all of them, so one
anomalous final reading — an outage, a partial last month, a single huge order —
inverts the reported direction of an otherwise obvious trend, and the reader has
no way to tell. There is a test for exactly this: a cleanly rising series with
one catastrophic final value is still reported as rising.

**`rolling_mean_7` is computed as `shift(1).rolling(7)`, not `rolling(7)`.**
Without the shift the window contains today's value, so the model is handed part
of the answer it is being asked to predict. The MAE would look excellent and
would not survive contact with a real unseen day.

## What is tested, and how to run it

```bash
python scripts/test_profiler.py   # semantic types on all samples + small-file cases
python scripts/test_router.py     # live routing + stubbed LLM failure paths
python scripts/test_worlds.py     # all three worlds, degradation, glass-box replay
python scripts/test_ml.py         # forecast honesty, guards, no-leakage split
python scripts/test_app.py        # the real Streamlit runtime, end to end
```

Each prints per-assertion `[OK ]`/`[FAIL]` lines and exits non-zero on failure.

What they actually cover:

- **`test_profiler.py`** — the expected semantic type of every column in every
  sample, including the `latency` decoy that must not become a coordinate and
  the numeric-coded `satisfaction` score that must become a category. Part 2
  proves the small-file row-count gate in both directions: a 100-row file's
  6-value column is categorical, its unique-per-row ID is still text, and above
  200 rows the ratio still rejects 20 values in 300 rows.
- **`test_router.py`** — part 1 routes all three samples for real. Part 2 stubs
  the LLM to prove the paths that only misbehave in production: markdown fences
  stripped, a hallucinated column name repaired from the profile, an unknown
  archetype rejected, prose instead of JSON degraded, and a real
  `ClientError` degrading to the rules instead of propagating.
- **`test_worlds.py`** — every world's happy path and every documented
  degradation (unparseable dates, all-null target, fewer than 2 periods, null
  coordinates, all points identical, `entity_col=None`, a single numeric
  column). Plus the glass-box replay described above.
- **`test_ml.py`** — that the verdict always matches the numbers (a losing model
  cannot produce a flattering verdict), that the split is chronological
  (demonstrated by checking the test window starts after the training window
  ends, not by reading the source), that the under-30-rows guard returns rather
  than raises, and that the returned code reproduces the reported MAEs.
- **`test_app.py`** — drives the real Streamlit runtime with `AppTest`: uploads
  each sample, checks the routed archetype and the badge, clicks Run forecast,
  changes the frequency, overrides the archetype three ways, and pulls every
  code block back off the rendered page to execute it. This one earned its
  keep — it caught a real bug on its first run (`st.line_chart` takes no `key`
  argument in Streamlit 1.62).

## Limitations and future work

**Only three archetypes.** Timeseries, geo and tabular cover a lot of real
files, but not network/graph data, not hierarchical data, not text corpora, and
not images. A dataset of nodes and edges routes to `tabular` and gets a
histogram, which is not wrong so much as beside the point. Adding an archetype
means a new module in `core/worlds/` plus one line in the router's prompt — the
contract is designed for it — but the three that exist are the three that exist.

**The small-file categorical rule is a trade-off, not a solution.** The ratio
test is now skipped below 200 rows, which fixes the common failure (a 100-row
file losing its category column). The cost is that between roughly 20 and 200
rows a column with up to 20 near-unique values will be typed as categorical when
it is really an identifier — a 50-row file with 18 distinct order references will
produce a grouped chart of 18 single-row bars. The absolute cap bounds the
damage, but the honest position is that categorical detection on small files is
guesswork with a sensible default, not a reliable inference.

**Forecast quality on short series is poor, and the app says so.** Below 30
usable rows it refuses outright. Above that it will often lose to the naive
baseline, and the verdict says so in plain language rather than quoting a MAE
that sounds impressive alone. On the sample data it loses badly — partly a real
result, and partly because forward-filling the gaps hands the naive predictor a
block of free zero-error days (on a filled day, today equals yesterday by
construction). That interaction is reported in the app rather than corrected for,
because quietly excluding filled days from the comparison would be tuning the
benchmark until the model wins. A better version would model the gaps explicitly,
or compare against a seasonal-naive baseline instead.

**Recursive forecasting compounds error.** Each predicted day becomes the next
day's `lag_1`, so day 30 of a 30-day horizon is a prediction built on 29
predictions. The chart shows it because the horizon control allows it; it should
be read with far less confidence than day 1.

**Streamlit is a prototype shell.** It was the right choice for getting the
pipeline visible quickly, but it reruns the entire script on every widget
interaction, which is why the Gemini call needs caching to avoid re-firing on a
slider drag. The intended architecture is FastAPI serving `core/` as JSON
endpoints with a React front end — `frontend/` is already scaffolded with Vite.
`core/` needs no changes for that migration, which was the point of forbidding
Streamlit imports there from the first commit.

**The LLM only classifies; it never generates code.** That is a deliberate
safety and determinism choice — the model picks from three fixed archetypes and
from column names that already exist, and everything it returns is validated
against the profile. It also caps the ceiling: the app cannot invent a
visualisation nobody wrote a template for. Generating chart code with an LLM and
sandboxing it is the obvious next step, and a substantially harder problem than
this project attempts.
