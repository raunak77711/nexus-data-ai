# AI Data Worlds

Upload a CSV. The app works out what the data *is*, decides which kind of
interactive world fits it, builds that world — and shows you the code behind
every chart it drew. Then you can ask it questions, and it will refuse to answer
the ones it cannot answer honestly.

**FastAPI + React.** `app.py` is a Streamlit dev harness kept for driving
`core/` without a browser; **it is not the deliverable.** The deliverable is
`backend/` + `frontend/`.

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

The same principle governs everything else in the app:

- The routing banner always states whether the **AI** or the **fallback rules**
  chose the archetype. It is never allowed to be ambiguous.
- The forecast is always quoted **next to the naive baseline it has to beat**,
  and a loss is displayed exactly as prominently as a win.
- Every world reports what it had to do to your data to plot it — rows dropped,
  dates that would not parse, categories omitted.
- The chat assistant is given **computed summaries only** and can never see a
  row, so it cannot invent one.

## Architecture

```
  ┌─ browser ──────────────────────────────────────────────────────────────┐
  │  frontend/  React 19 + Vite, hand-written CSS, react-plotly.js          │
  │                                                                        │
  │   App.jsx ── session state, every fetch, loading + error for each       │
  │     ├── UploadPane      vanilla DnD: addEventListener / dataset /       │
  │     │                   classList, depth-counted dragenter/leave        │
  │     ├── StatsStrip · ProfileTable · RoutingBanner · ArchetypeSelect     │
  │     ├── WorldView ──▶ PlotFigure (JSON.parse → <Plot/>)                 │
  │     │              └▶ CodePanel   vanilla clipboard read from the       │
  │     │                             rendered DOM + rAF scroll-spy         │
  │     ├── ForecastPanel   predictions vs actuals, both MAEs, verdict      │
  │     └── ChatPanel       reply + the context blocks it was grounded on   │
  └───────────────────────────────┬────────────────────────────────────────┘
                                  │  JSON over HTTP (CORS: :5173 / :5174)
                                  ▼
  ┌─ backend/  the ONLY package that knows about HTTP ─────────────────────┐
  │                                                                        │
  │   main.py          app factory · CORS · 3 exception handlers, so no     │
  │                    route can leak a traceback                          │
  │   routers/         health · upload · samples · route · world ·          │
  │                    forecast · chat                                     │
  │   models.py        pydantic request/response contracts                 │
  │   session.py       {uuid → parsed DataFrame + profile + routing +      │
  │                    last world stats + last forecast}, TTL + LRU        │
  │   serialisation.py numpy / NaN / Figure / DataFrame → JSON             │
  └───────────────────────────────┬────────────────────────────────────────┘
                                  │  DataFrames and plain dicts
                                  ▼
  ┌─ core/  framework-agnostic — imports neither streamlit nor fastapi ────┐
  │                                                                        │
  │   profiler.py ──▶ profile dict {columns, semantic types, flags}         │
  │        │                                                               │
  │        ▼                                                               │
  │   router.py ────▶ routing dict {archetype, target/time/entity/lat/lon}  │
  │        │            ├── Gemini (google-genai)   source="llm"            │
  │        │            └── rule-based fallback     source="fallback"       │
  │        ▼                                                               │
  │   worlds/                    ml.py              chat.py                │
  │    ├── timeseries.py         forecast() +       answers from computed   │
  │    ├── geo.py                naive baseline     summaries only — has    │
  │    ├── tabular.py                               NO DataFrame parameter  │
  │    └── _glassbox.py  ◀── renders code, execs it, returns the figure     │
  └────────────────────────────────────────────────────────────────────────┘

                     app.py (Streamlit) also sits directly on core/
                     — a dev harness, not the deliverable
```

`core/` is unchanged from the Streamlit version. Nothing in it imports a web
framework; every module takes plain inputs (DataFrames, dicts, scalars) and
returns plain outputs (dicts, DataFrames, plotly Figures, strings). That is why
replacing Streamlit with FastAPI + React was a rewrite of the presentation layer
rather than a rewrite of the project. The test for where logic belongs: *would
it still be true if the UI were a REST endpoint?* If yes, it goes in `core/`.

## Setup

### Docker (both services, hot reload)

```bash
cp .env.example .env          # paste your Google AI Studio key into it
docker compose up --build
```

- frontend → <http://localhost:5173>
- backend → <http://localhost:8000>, interactive API docs at
  <http://localhost:8000/docs>

Source is bind-mounted, so edits on the host reload in the container. The
backend regenerates `samples/` on start (the generator is seeded, so the files
are identical every time). `docker compose down` stops it.

Three details in `docker-compose.yml` worth knowing about, all commented in the
file:

- **The anonymous `- /app/node_modules` volume.** Without it, the source bind
  mount replaces the container's `node_modules` with the Windows host's, whose
  binaries cannot run under Alpine.
- **`VITE_API_BASE=http://localhost:8000/api`, not `http://backend:8000`.** The
  *browser* makes that request, not the container, so it needs the host-published
  port. Using the compose service name here is the classic mistake and produces
  a connection error that looks like the API is down.
- **`CHOKIDAR_USEPOLLING=true`.** Bind mounts on Windows and macOS do not deliver
  inotify events into the container, so Vite's watcher never fires and hot
  reload silently stops working.

### Local (no Docker)

```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

cp .env.example .env             # then paste your key into it
python scripts/make_samples.py   # generates samples/
```

Two terminals:

```bash
# terminal 1 — API on :8000
uvicorn backend.main:app --reload

# terminal 2 — UI on :5173
cd frontend
npm install
npm run dev
```

The key comes from [Google AI Studio](https://aistudio.google.com/apikey) and
goes in `.env` as `GOOGLE_API_KEY`. `.env` is gitignored.

**The app runs without a key.** Routing falls back to the built-in rules and the
badge turns amber. The worlds, the code panels and the forecast work identically.
Only the chat assistant needs the key, and without one it says so rather than
guessing.

> **Note on the free tier:** Google AI Studio's free tier allows 20 requests per
> day on `gemini-3.6-flash`. Once that is exhausted the API returns
> `429 RESOURCE_EXHAUSTED`, routing degrades to the amber fallback path, and
> chat reports itself unavailable. That is the designed behaviour, not a fault —
> but if you are demoing, check the quota first.

### The Streamlit harness

```bash
streamlit run app.py
```

Kept because `scripts/test_app.py` drives it through Streamlit's own test
runtime, which exercises `core/` end to end without a browser. **It is not the
deliverable** and it is not part of the Docker setup.

## API

Base path `/api`. Full OpenAPI schema at `/docs` when the server is running.

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/health` | — | `{status, version, sessions}` |
| `POST` | `/api/upload` | multipart `file` | `{session_id, filename, n_rows, n_cols, profile}` |
| `GET` | `/api/samples` | — | `[{key, filename, label, description, n_bytes}]` |
| `POST` | `/api/samples/{key}` | — | same shape as `/upload` |
| `GET` | `/api/route/{sid}` | — | `{archetype, time_col, entity_col, target_col, lat_col, lon_col, reasoning, source}` |
| `POST` | `/api/world/{sid}` | `{archetype, params:{freq?, rolling_window?, time_filter?}}` | `{figures_json, stats, code, warnings, status, message, archetype}` |
| `POST` | `/api/forecast/{sid}` | `{horizon}` | `{status, metrics, beats_baseline, verdict, predictions, future, feature_importances, code, warnings, message}` |
| `POST` | `/api/chat/{sid}` | `{message, history:[{role, content}]}` | `{reply, grounded_on, available}` |

Status codes: **400** unreadable, empty or non-CSV upload · **404** unknown or
expired session · **413** file over 50MB · **422** invalid parameters ·
**500** an unexpected server error, logged with its traceback and returned as
one clean sentence. Every failure at every status returns the same one-field
shape, `{"detail": "<sentence>"}`, so the frontend has exactly one error branch.

Two serialisation rules the API is built around, because they are where a
pandas app breaks when it grows an HTTP boundary:

- **Figures are JSON strings**, not nested objects. `figures_json` is
  `{name: fig.to_json()}`. Plotly's own encoder knows how to render numpy
  arrays, datetime axes and colour scales in the exact shape plotly.js expects;
  re-encoding through a generic dict walk is a reliable source of subtly broken
  charts.
- **`predictions` and `future` are records with the index promoted to a `date`
  field**: `[{date, actual, predicted}, …]` and `[{date, predicted}, …]`.
  `df.to_dict('records')` alone throws the DatetimeIndex away and produces a
  chart plotted against row number.

`backend/serialisation.py` handles numpy scalars, `NaN`/`Infinity` (mapped to
`null` — `json.dumps` accepts both by default and emits tokens that are not
valid JSON), `NaT`, `pd.NA` and Timestamps. `scripts/test_api.py` round-trips
every payload through `json.dumps(..., allow_nan=False)`, deliberately strict:
a payload that only survives a permissive encoder has not survived.

## How it works — the five stages

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
`source="fallback"`. **The UI always tells you which path ran** — green badge for
AI, amber for the rules.

Profiling and routing both run at upload time and are cached on the session, so
`GET /api/route` is a dict lookup. That is not just a latency saving: recomputing
would make routing non-idempotent, and a second LLM call could return a different
archetype from the one the world was built with, leaving the banner disagreeing
with the chart.

### 3. Build a world (`core/worlds/`)

| Archetype | Figures | Controls |
|---|---|---|
| `timeseries` | resampled line chart with rolling-mean overlay; split by category (top 6 by volume) | D/W/M resample, rolling window |
| `geo` | scatter map on OpenStreetMap tiles, points coloured *and* sized by the measure, view fitted to the data's bounding box | time range |
| `tabular` | distribution histogram with mean line; mean-by-category bars (top 15); correlation heatmap | none |

Every world returns the same shape — `figures`, `stats`, `code`, `warnings`,
`status` — so the presentation layer renders any archetype through one code path.

### 4. Forecast (`core/ml.py`)

For timeseries only, on request: a `RandomForestRegressor` over `lag_1`,
`lag_7`, `rolling_mean_7`, `day_of_week` and `month`, scored on a chronological
last-20% split, always reported next to a naive "tomorrow looks like today"
baseline.

### 5. Ask about it (`core/chat.py`)

A chat panel answers questions about the dataset — what it is about, which
column has the most missing values, what the trend was, whether the forecast beat
the baseline, why that archetype was chosen.

**It can never invent a number, and that guarantee is structural rather than a
prompt instruction.** The model receives only the profile, the routing, the
built world's computed statistics and the forecast metrics. `build_context()`
and `answer()` **have no DataFrame parameter and no rows parameter** — there is
no channel through which a row could reach the model. A missing function
parameter is a stronger guarantee than a filter, because a filter can be got past.

Three further defences:

- The system prompt states that every number must be copied from the context,
  and — more importantly — that *"I only have the summary, not the rows"* is a
  **successful** answer rather than a failure to avoid. Models guess when the
  prompt implies an answer is expected.
- Each reply carries a **`grounded_on`** list naming the context blocks it used
  (e.g. `["profile", "timeseries_stats"]`), displayed under the reply in the UI.
  That list is **validated**, not trusted: the model's claim is intersected with
  the blocks actually supplied, the same trust-but-verify pattern the router
  applies to a proposed column name. A model citing `forecast_metrics` when no
  forecast has run would otherwise be presenting an invention with a citation
  attached, which is worse than presenting it bare.
- If the API fails, chat says it is unavailable. There is **no fallback
  answerer**, because the only thing one could do is guess.

Honestly stated: the profile includes up to ten example values per *categorical*
column, which are real cell contents. They are a bounded, low-cardinality
vocabulary already shown on screen, and `router.py` already sends three of them.
No numeric, text, date or coordinate cell is ever sent.

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

### Three more decisions worth naming

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

**The session store caches a parsed DataFrame, so `/world` and `/forecast` never
re-read the upload.** The alternative is re-parsing the CSV on every slider
nudge. The cost is that the store is a process-local dict — see Limitations.

## Design and front-end notes

Hand-written CSS throughout: no Tailwind, no component library, one stylesheet
per component plus `styles/tokens.css` (every custom property) and
`styles/base.css` (reset, focus, utilities).

- **Type:** Space Grotesk (display) / Inter (body, tabular figures) / JetBrains
  Mono (code), on a 1.25 modular scale from a 16px base. The one deviation from
  the ratio is documented in `tokens.css` with its reason.
- **Space:** an 8px scale with two half-steps.
- **Colour:** a warm neutral ramp, one accent, a rationed second "spark", plus
  semantic success/warning/error tuned to the same warmth. Dark mode via
  `prefers-color-scheme` redefines ~20 role variables, not a second stylesheet.
  **Every pair was measured against WCAG AA 4.5:1** and three colours were
  darkened to clear it. Colour is never the only channel: every type badge
  prints its type, every null bar prints its percentage, and the AI/fallback
  badge says which in words.
- **Motion:** nothing over 250ms. `prefers-reduced-motion` collapses durations
  rather than removing feedback, except where the motion is a large travelling
  gradient, which is suppressed outright.
- **Semantics:** `header`/`main`/`section`/`article`/`aside`/`footer`, a real
  `<table>` with `<caption>` and `scope`, `<fieldset>`/`<legend>` for the
  segmented controls, `<details>` for disclosures, labelled inputs throughout, a
  skip link, and one global `:focus-visible` ring that nothing is allowed to
  remove.
- **Responsive** to tablet and below; the two-column layout appears at 1080px,
  where a 380px sidebar still leaves the charts wide enough to read their axes.

**Two features use the DOM API directly rather than React idioms**, and both are
places where that is genuinely the better tool:

1. **`UploadPane` drag-and-drop** — `addEventListener`, `element.dataset`,
   `classList`. `dragover` fires continuously while the pointer is over the
   target, so routing it through `useState` re-renders the pane many times a
   second; writing a data attribute mutates one property and lets CSS select on
   it. And `dragleave` fires when the cursor crosses onto a *child* element, so
   the naive version flickers — the fix is an enter/leave depth counter, which is
   DOM-level bookkeeping a hook would make slower and no clearer.
2. **`CodePanel` clipboard + scroll-spy** — the copy button reads the code out of
   the **rendered DOM** with `querySelector` + `textContent`, not from the prop
   it was rendered from, so it provably copies what is on screen; for a glass box
   that is the argument, not a detail. There is an `execCommand` fallback for
   non-secure origins. The scroll-spy writes a CSS custom property for the header
   progress bar, batched into `requestAnimationFrame` so a scroll never causes a
   synchronous layout.

Both are commented in place explaining why.

`plotly.js` is assembled from `lib/core` plus only the five trace types `core/`
can emit (scatter, bar, histogram, heatmap, scattermap) — 2.2MB rather than the
4.9MB default bundle.

## What is tested, and how to run it

```bash
python scripts/test_profiler.py   # semantic types on all samples + small-file cases
python scripts/test_router.py     # live routing + stubbed LLM failure paths
python scripts/test_worlds.py     # all three worlds, degradation, glass-box replay
python scripts/test_ml.py         # forecast honesty, guards, no-leakage split
python scripts/test_api.py        # the FastAPI layer: contracts + serialisation
python scripts/test_chat.py       # the chat assistant cannot fabricate
python scripts/test_app.py        # the Streamlit harness, end to end
```

Against a **running** server (after `docker compose up`, or a local uvicorn):

```bash
python scripts/verify_live.py     # the whole journey over a real socket
```

Frontend:

```bash
cd frontend
npm run lint    # oxlint, clean
npm run build   # production build
```

Each Python suite prints per-assertion `[OK ]`/`[FAIL]` lines and exits non-zero
on failure.

What they actually cover:

- **`test_profiler.py`** — the expected semantic type of every column in every
  sample, including the `latency` decoy that must not become a coordinate and
  the numeric-coded `satisfaction` score that must become a category. Part 2
  proves the small-file row-count gate in both directions.
- **`test_router.py`** — part 1 routes all three samples for real. Part 2 stubs
  the LLM to prove the paths that only misbehave in production: markdown fences
  stripped, a hallucinated column name repaired from the profile, an unknown
  archetype rejected, prose instead of JSON degraded, and a real `ClientError`
  degrading to the rules instead of propagating.
- **`test_worlds.py`** — every world's happy path and every documented
  degradation (unparseable dates, all-null target, fewer than 2 periods, null
  coordinates, all points identical, `entity_col=None`, a single numeric column).
  Plus the glass-box replay described above.
- **`test_ml.py`** — that the verdict always matches the numbers (a losing model
  cannot produce a flattering verdict), that the split is chronological
  (demonstrated by checking the test window starts after the training window
  ends, not by reading the source), that the under-30-rows guard returns rather
  than raises, and that the returned code reproduces the reported MAEs.
- **`test_api.py`** — every endpoint against all three samples via
  `TestClient`: response shapes, the archetype override not mutating the cached
  routing, and the error paths (404 dead session, 400 non-CSV, 400 empty, 413 on
  a real 52MB body, 422 on every out-of-range parameter). Every payload is
  round-tripped through `json.dumps(allow_nan=False)`. Also covers the session
  store's TTL expiry and LRU eviction directly.
- **`test_chat.py`** — three parts. **Structural:** plants sentinel values in a
  DataFrame and proves they cannot appear in the assembled context, and asserts
  neither public function has a DataFrame parameter. Needs no network, and is
  the strongest guarantee available. **Plumbing** (stubbed model): a claimed
  source that was never supplied is stripped, an API exception degrades to
  "unavailable", non-JSON output is *not* passed off as an answer, a missing key
  is handled. **Live:** asks the real model an unanswerable question ("what was
  the revenue on 3 March?") and asserts it declines without stating the value,
  with a control question to prove it is not merely mute. The live part prints a
  loud `[SKIP]` when there is no usable key, because a skipped test that looks
  like a pass is worse than no test.
- **`test_app.py`** — drives the Streamlit harness with `AppTest`, pulling every
  code block back off the rendered page to execute it. It caught a real bug on
  its first run (`st.line_chart` takes no `key` argument in Streamlit 1.62).
- **`verify_live.py`** — not a unit suite: it walks upload → profile → route →
  world → code → forecast → chat against a real server over a real socket, in
  the same order the browser does. A green `test_api.py` says the logic works; a
  green `verify_live.py` says the deployment does.

## Limitations and future work

**The session store is an in-memory dict, and that is single-process only.** It
caches a parsed DataFrame per upload, which is the point — the alternative is
re-parsing the CSV on every interaction. But run `uvicorn --workers 2` and half
the requests land on a worker that has never heard of the session id, producing
an intermittent 404 that looks like a frontend bug. It also dies with the
process, so a reload during a demo loses every session. The production answer is
Redis for the session metadata plus object storage (or Parquet on a shared
volume) for the frame itself; `backend/session.py` keeps its interface narrow
(`create`/`get`/`delete`) precisely so that swap is a change to one file. There
is a TTL sweep at one hour and an LRU cap at 32 sessions so an abandoned upload
is not held forever, but neither of those makes it horizontally scalable.

**The chat assistant is limited to summary context, by design.** It cannot tell
you the value on a specific date, find outlier rows, or answer anything that
needs the data itself, and it will say so rather than guess. That is the correct
trade for this project — a chatbot that hallucinates one correlation destroys the
credibility of every honest answer around it — but it is a real limit, not a
technicality. The next step is not "give it the rows": it is giving it a small
set of *verified tools* (a `describe` on a named column, a value lookup at a
named index) whose outputs are computed by pandas and returned to it, so the
answer set widens without the fabrication risk ever reopening.

**Only three archetypes.** Timeseries, geo and tabular cover a lot of real files,
but not network/graph data, not hierarchical data, not text corpora, and not
images. A dataset of nodes and edges routes to `tabular` and gets a histogram,
which is not wrong so much as beside the point. Adding an archetype means a new
module in `core/worlds/` plus one line in the router's prompt — the contract is
designed for it — but the three that exist are the three that exist.

**The small-file categorical rule is a trade-off, not a solution.** The ratio
test is skipped below 200 rows, which fixes the common failure (a 100-row file
losing its category column). The cost is that between roughly 20 and 200 rows a
column with up to 20 near-unique values will be typed as categorical when it is
really an identifier — a 50-row file with 18 distinct order references will
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

**No authentication, and the session id is the only protection.** It is a uuid4,
so it is unguessable, but anyone holding one can read that upload. Fine for a
local single-user tool; not fine on a public host, which would need real auth
before the in-memory store is replaced by anything shared.

**The LLM only classifies; it never generates code.** That is a deliberate
safety and determinism choice — the model picks from three fixed archetypes and
from column names that already exist, and everything it returns is validated
against the profile. It also caps the ceiling: the app cannot invent a
visualisation nobody wrote a template for. Generating chart code with an LLM and
sandboxing it is the obvious next step, and a substantially harder problem than
this project attempts.

**The Docker setup is a development one.** Bind mounts, dev servers, hot reload.
A production compose would build the frontend to static files behind nginx and
run uvicorn under gunicorn with several workers — which this application cannot
currently do, for the session-store reason above. The two are linked, and fixing
the second is what unblocks the first.
