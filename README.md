# Nexus Data AI

**Upload any dataset. The AI reads it, checks it, analyses it, and tells you
what is in it — before you ask anything.**

Most tools in this space hand you a CSV parser and a chat box and leave the
analysis to you. The problem that solves is not the problem people have. The
problem people have is that they are holding a spreadsheet they do not
understand and do not know what to ask about it.

So this one does not wait. The moment a file lands it is profiled, audited for
quality, scanned for trends, relationships and anomalies, given a set of charts
chosen from its own columns, and written up as a briefing:

> **I've analysed your data. Here are the 5 things you should know.**

Then you can ask it anything, in plain English, and every answer is a real
calculation over your real rows.

```
add a file  →  it gets read, checked and analysed  →  here is what I found,
                                                      and here is what to ask
```

## The claim this product is built around

**No number this application displays is ever written by a language model.**

That is a strong claim, and most products that make it are relying on a system
prompt saying "do not invent numbers". A prompt is a request. This is enforced:

1. Every figure is computed in Python, by pandas, from the user's own rows.
2. The model is asked only to write the *sentence around* a computed figure.
3. Its output goes through [`core/grounding.py`](core/grounding.py), which
   extracts every numeric token from the text and checks each one against the
   set of numbers that were actually supplied to it.
4. Text containing a figure nobody computed is **discarded**, and the
   deterministic sentence is shown instead.

The consequence is worth stating plainly, because it is why the feature is safe
to ship: the worst a hallucinating model can do here is produce prose that reads
slightly more stiffly than it might have. It cannot put a false figure on the
screen, because a false figure is by construction one that is not in the allowed
set.

Having built that guarantee, the interface does not hide it. Every claim on
screen carries a small typographic mark saying how it was produced:

| Mark | Means |
| --- | --- |
| `COMPUTED` | pandas produced the number *and* the wording. A measurement. |
| `AI WORDING` | pandas produced the numbers; AI wrote the sentence around them. Every figure in it was checked. |
| `AI SUGGESTION` | an AI inference from the findings. **Not** a measurement. |

That distinction is the one thing a reader most needs and is almost never given.

**The app runs completely without an API key.** Every check, every chart, every
finding and every calculation is local. What a key buys is fluency and a wider
range of understood phrasings — never correctness.

## What it does

### It analyses without being asked

Structure, row and column counts, types, missing values, duplicates, important
variables, correlations, trends, outliers, anomalies, distributions and quality
problems — all computed on upload, then ranked *across* those sources so that a
serious data problem outranks an interesting trend. A trend computed from broken
data is not a trend.

### It tells you a story, not a wall of charts

Findings arrive as sentences, ordered by how much they matter, each one
expandable to the chart or the rows that prove it.

### It builds a dashboard shaped like your data

Not a template. [`core/dashboard.py`](core/dashboard.py) scores every chart the
columns could support — trend, ranking, relationship, correlation grid,
distribution, spread-by-group, map — and builds the winners. A sales export
leads with a line chart and a survey export leads with a distribution, from one
rule set. Each panel says *why* it is on the page.

### It audits your data, and can repair it

[`core/health.py`](core/health.py) scores the file out of 100 across ten checks,
and the score decomposes into a list of named issues you can argue with. Where a
repair is safe it is offered — but never applied without review:

```
here is what is wrong  →  here is exactly what I would change  →  change it
                                                               →  undo it
```

Your original file is kept intact for the life of the dataset, so "undo" is
dropping a reference rather than computing an inverse — which matters, because
half of these operations have no inverse.

### It answers anything, and suggests what to ask next

Ask in plain English. The assistant plans a calculation, runs it over your rows,
and explains the result — then offers follow-ups that are each a *different kind*
of next question rather than three rewordings of the same one.

### It explains anything, at two levels

Every chart, finding and issue has **Explain this**, in two genuinely different
registers: Simple is forbidden from naming a statistical method at all;
Technical must state the method and at least one way the result could mislead.

### It remembers, compares and reports

Datasets persist to disk, so "My datasets" survives a restart. Any two can be
compared — growth, decline, new categories, distribution shifts, quality changes
— and any one can be turned into a report with an executive summary, findings,
charts, quality caveats and recommendations, printable straight to PDF.

## Architecture

```
  ┌─ browser ─────────────────────────────────────────────────────────────┐
  │  frontend/  React 19 + Vite, hand-written CSS, react-plotly.js         │
  │                                                                       │
  │   App.jsx ── which page, the session, the detail mode                 │
  │     │        useRoute() keeps it in the hash, so Back works           │
  │     │                                                                 │
  │     ├── Home         hero = a SPECIMEN FINDING, not a dashboard shot   │
  │     ├── Analyze  ┬── Analyzing  stages advanced by real responses,    │
  │     │            │              never a timer                         │
  │     │            ├── Workspace  Story · Charts · Health · Actions ·   │
  │     │            │              Rows · Report · Compare               │
  │     │            └── useAnalysis()  runs the whole analysis, owns its │
  │     │                 stages, its cache and its race protection       │
  │     ├── Datasets     the library: open, inspect, delete               │
  │     └── About        the argument for the product                     │
  │                                                                       │
  │   NavBar      one bar on every page: Home · Analyze · Datasets · About │
  │   Assistant   on EVERY page, home included, context-aware; reachable  │
  │               from the navbar and from a floating launcher            │
  │   Provenance  the mark on every claim: computed / worded / suggested  │
  └──────────────────────────────┬────────────────────────────────────────┘
                                 │  JSON over HTTP
                                 ▼
  ┌─ backend/  the ONLY package that knows about HTTP ────────────────────┐
  │   main.py           app factory · CORS · 3 handlers, so no route can  │
  │                     leak a traceback                                  │
  │   routers/          health · upload · samples · route · world ·       │
  │                     forecast · chat · assistant · insights · chart ·  │
  │                     simulate · preview · analysis · quality ·         │
  │                     explain · datasets · report                       │
  │   routers/_analysis.py  computes each artefact ONCE and caches it on  │
  │                     the session, so the story page and the exported   │
  │                     report can never disagree                         │
  │   session.py        MEMORY: parsed frames, bounded, evictable         │
  │                     DISK:   the uploaded bytes + an index — durable   │
  │                     eviction loses nothing; the file is re-read       │
  │   serialisation.py  numpy / NaN / Figure / DataFrame → JSON           │
  └──────────────────────────────┬────────────────────────────────────────┘
                                 │  DataFrames and plain dicts
                                 ▼
  ┌─ core/  framework-agnostic — imports neither streamlit nor fastapi ───┐
  │                                                                       │
  │   profiler.py    what each column IS, not how it is stored            │
  │   router.py      which archetype, via llm.py or rules                 │
  │   health.py      the quality doctor: 10 checks, a score that          │
  │                  decomposes, and a FIX PROPOSAL — never an action     │
  │   cleaner.py     applies only what was approved. Returns a NEW frame  │
  │                  and a receipt of what it actually did                │
  │   dashboard.py   scores every possible chart, builds the winners      │
  │   insights.py    trends · relationships · anomalies · segments        │
  │   story.py       the briefing, recommendations, suggested questions   │
  │   explain.py     one result, two registers                           │
  │   compare.py     what changed between two files                      │
  │   followup.py    what to ask next — one per KIND of move             │
  │   report.py      assembles; computes nothing                         │
  │   grounding.py   ◀── THE CHECK. Shared by every prose path.          │
  │   charts.py      a spec → one of seven whitelisted charts + its code  │
  │   tools.py       the calculator the assistant is allowed to drive     │
  │   chat.py        plans a calculation, never performs one — has NO     │
  │                  DataFrame parameter, only a `compute` callable       │
  │   worlds/_glassbox.py  renders code, execs it, returns the figure     │
  │   llm.py         the ONLY module that talks to a provider.            │
  │                  deepseek (httpx) | gemini | off. One LLMError.       │
  └───────────────────────────────────────────────────────────────────────┘
```

Nothing in `core/` imports a web framework. Every module takes plain inputs and
returns plain outputs, which is why the presentation layer can be replaced
without touching the analysis. The test for where logic belongs: *would it still
be true if the UI were a REST endpoint?* If yes, it goes in `core/`.

## The glass box

Every chart ships with the pandas that produced it — and the relationship is
inverted from the usual one, which is what makes the claim trustworthy. The code
string is rendered **first**, then **executed**, and the figure you see is
whatever that snippet produced. There is one artefact, so divergence is
impossible rather than merely unlikely. `scripts/test_worlds.py` proves it by
re-running every snippet in a fresh namespace and asserting the replayed
figure's JSON is identical.

Shown in **Advanced** mode only. A beginner does not need to be shown code they
cannot read in order to trust the chart above it; an expert does, and Advanced
is who that is for.

## Setup

### Docker (both services, hot reload)

```bash
cp .env.example .env          # paste your DeepSeek key into it
docker compose up --build
```

- frontend → <http://localhost:5173>
- backend → <http://localhost:8000>, interactive API docs at
  <http://localhost:8000/docs>

Source is bind-mounted, so edits on the host reload in the container. The
backend regenerates `samples/` on start (the generator is seeded, so the files
are identical every time). `docker compose down` stops it.

Four details in `docker-compose.yml` worth knowing about, all commented in the
file:

- **The anonymous `- /app/node_modules` volume.** Without it, the source bind
  mount replaces the container's `node_modules` with the Windows host's, whose
  binaries cannot run under Alpine.
- **`VITE_API_BASE=http://localhost:8000/api`, not `http://backend:8000`.** The
  *browser* makes that request, not the container, so it needs the host-published
  port. Using the compose service name here is the classic mistake and produces
  a connection error that looks like the API is down.
- **The named `nexus-store` volume.** Uploaded datasets and their index live
  there, which is what makes "My datasets" survive a restart. Named rather than
  bind-mounted on purpose: the contents are users' uploaded files, not source,
  and binding them into the repo would put other people's data in a directory
  people commit from. `docker compose down` keeps them; `down -v` is the
  deliberate way to discard them.
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

### The API key

The default provider is **DeepSeek**. Get a key from
[platform.deepseek.com](https://platform.deepseek.com/api_keys) and put it in
`.env` as `DEEPSEEK_API_KEY`. `.env` is gitignored.

```ini
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
```

To use Google Gemini instead, set `AI_PROVIDER=gemini` and `GOOGLE_API_KEY`
([key here](https://aistudio.google.com/apikey)). Nothing else changes: both
providers go through `core/llm.py`, which is the only module in the project
that talks to one. Adding a third is one function there and no edits anywhere
else — the previous arrangement had provider details in two modules that had to
agree, and setting `AI_PROVIDER` to anything they did not both name silently
turned the model off.

`GET /api/health` reports which provider is live, and why not when it is not:

```json
{"status":"ok","assistant":{"available":true,"provider":"deepseek","model":"deepseek-chat","reason":""}}
```

**The app runs without a key.** Routing falls back to the built-in rules, and
the charts, the findings and the forecast are computed locally and work
identically — they never involved a model. The data assistant still answers any
question it can recognise, in templated wording rather than its own, and the
help chat answers from a built-in FAQ. What a key buys is fluency and a wider
range of understood phrasings, not correctness. **No number this app displays,
anywhere, is ever written by a model.**

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
| `GET` | `/api/health` | — | `{status, version, sessions, assistant:{available, provider, model, reason}}` |
| `POST` | `/api/upload` | multipart `file` | `{session_id, filename, n_rows, n_cols, profile}` |
| `GET` | `/api/samples` | — | `[{key, filename, label, description, n_bytes}]` |
| `POST` | `/api/samples/{key}` | — | same shape as `/upload` |
| `GET` | `/api/route/{sid}` | — | `{archetype, time_col, entity_col, target_col, lat_col, lon_col, reasoning, source}` |
| `POST` | `/api/world/{sid}` | `{archetype, params:{freq?, rolling_window?, time_filter?}}` | `{figures_json, stats, code, warnings, status, message, archetype}` |
| `POST` | `/api/forecast/{sid}` | `{horizon}` | `{status, metrics, beats_baseline, verdict, predictions, future, feature_importances, code, warnings, message}` |
| `POST` | `/api/chat/{sid}` | `{message, history:[{role, content}]}` | `{reply, grounded_on, available, answered_by, tool, action, table, data}` |
| `POST` | `/api/assistant` | `{message, history, session_id?}` | `{reply, available, answered_by, about, action, table}` |
| `GET` | `/api/insights/{sid}` | — | `{summary, counts, shape, insights:[{kind, tone, headline, detail, why, evidence, action}]}` |
| `POST` | `/api/chart/{sid}` | `{chart, x?, y?, lat?, lon?, agg?, freq?, limit?, ascending?}` | `{figure_json, code, title, spec, warnings}` |
| `GET` | `/api/simulate/{sid}/options` | — | `{available, columns, default_target, suggested_driver, min_pct, max_pct}` |
| `POST` | `/api/simulate/{sid}` | `{pct_change, target?, driver?}` | `{status, message, caveats, basis, baseline, projected, delta, confidence}` |
| `GET` | `/api/preview/{sid}?limit=` | — | `{columns, rows, profile, n_rows_total, n_rows_returned, truncated}` |

### The autonomous analysis

These are the routes the app calls **without being asked**, fired the moment an
upload lands. Each is separate rather than bundled so the page fills in as each
finishes — and so the progress indicator has real stages to report instead of
one spinner over one long request.

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/briefing/{sid}` | — | `{headline, summary, points:[{id, kind, label, icon, tone, title, body, link, written_by}], source, n_considered}` |
| `GET` | `/api/dashboard/{sid}` | — | `{kpis, panels:[{id, kind, title, question, why, figure_json, code, spec, warnings}], note, n_considered}` |
| `GET` | `/api/health-report/{sid}` | — | `{score, grade, verdict, headline, issues, counts, n_fixable, checks_run, clean, sampled, n_rows, n_cols}` |
| `GET` | `/api/recommendations/{sid}` | — | `{recommendations:[{title, body, basis, confidence}], source, disclaimer}` |
| `GET` | `/api/questions/{sid}` | — | `{questions:[{text, why}], source}` |
| `GET` | `/api/timeline/{sid}` | — | `{events:[{stage, message, at, detail}], n_events}` |
| `POST` | `/api/explain/{sid}` | `{target, ref, level}` | `{text, level, source, title}` |

`/api/health-report` is named that way because `/api/health` already means "is
the server up" — the route the frontend polls to decide whether to show its
offline banner. Two routes differing only by a path parameter is exactly the
collision that produces an outage banner in front of an audience.

`/api/explain` takes a **target and a reference** — an insight id, an issue id,
a panel id — rather than a description of what is on screen. That is deliberate:
the grounding check compares the explanation against numbers the *server*
computed, and a client that posted its own figures would be supplying both sides
of the check.

### Cleaning, datasets and reports

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/clean/{sid}/plan` | `{issue_ids}` | `{steps, n_steps, note}` — **changes nothing** |
| `POST` | `/api/clean/{sid}` | `{issue_ids}` | `{summary, log, applied, rows_before, rows_after, cells_changed, health, is_cleaned}` |
| `POST` | `/api/clean/{sid}/revert` | — | same shape; restores the original file |
| `GET` | `/api/export/{sid}?original=` | — | `text/csv` attachment |
| `GET` | `/api/datasets` | — | `[{id, filename, n_rows, n_cols, health_score, health_grade, is_cleaned, loaded, …}]` |
| `DELETE` | `/api/datasets/{sid}` | — | `204`, and the stored bytes are removed |
| `POST` | `/api/compare/{sid}` | `{other_id}` | `{comparable, changes, columns, shape, summary, n_changes, source}` |
| `GET` | `/api/report/{sid}` | — | `{title, subtitle, generated_at, sections, meta}` |

The plan step exists because *"I found 342 issues — fix them?"* is not informed
consent. Somebody approving a clean is agreeing to specific operations on
specific columns, and they cannot agree to what they have not seen.

`issue_ids: null` and `issue_ids: []` are **different requests** — everything,
and nothing — and the server treats them differently. Conflating them is how a
"fix nothing" click becomes a "fix everything" action.

`/api/compare/{sid}` treats the **other** dataset as the baseline and the
current one as the result: "what changed to arrive at what I am looking at now".
Leaving that ambiguous would mean every direction in the report could be read
backwards, and a report saying revenue fell when it rose is worse than none.

`/api/report` returns **structured sections, not a rendered PDF**. The browser
already has a layout engine, the fonts and the exact styling the user has been
looking at; reproducing all three server-side would only produce a document that
does not match what they approved. "Save as PDF" is `window.print()` against a
print stylesheet.


`/api/assistant` is the one endpoint the chat bubble calls, on every screen. Its
`session_id` is optional and an unknown one is not an error — see
[The two assistants](#the-two-assistants). `/api/chat/{sid}` is the grounded
data assistant on its own, kept as a direct route because it is what
`scripts/verify_live.py` and `scripts/test_api.py` exercise.

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

## How it works — the seven stages

### 1. Profile (`core/profiler.py`)

Every column is assigned exactly one *semantic* type — what it means, not what
dtype pandas gave it: `datetime`, `numeric`, `categorical`, `geo_lat`,
`geo_lon`, `text`. The result is a compact, JSON-safe dict that every later
stage consumes.

### 2. Route (`core/router.py`)

The profile summary — never the rows — is sent to the configured model via
`core/llm.py`, which picks one of three archetypes (`timeseries`, `geo`,
`tabular`) and the columns that world needs. The answer is validated against the
profile before use, so a hallucinated column name degrades to the rule-based pick
rather than crashing a chart three layers down. If the API is unavailable, the
key is missing, or the response fails validation, deterministic rules take over
and the result is marked `source="fallback"`.

The response still carries `source` and `reasoning`, and
`scripts/verify_live.py` asserts on both. The simplified UI no longer shows a
badge for it: which of two internally-equivalent paths chose your chart is a
fact about the machine, not about your data, and it was one more thing on screen
to interpret. Ask the helper *"why this chart?"* and it will tell you.

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

### 4. Find things worth saying (`core/insights.py`)

Runs six passes over the frame — change over time, columns that move together,
rows far outside the normal range, standout categories, gaps and duplicates in
the data itself, and whether a forecast is even worth attempting — and returns
each finding as a card with a headline, a plain-language detail, a "why it
matters" line, the numbers it came from, and a chart spec that shows it.

**No LLM writes a finding.** Every number is computed by pandas on the user's
own rows and the phrasing is templated. A language model is a good writer and a
bad calculator, and an insight card is the worst possible place to be
approximately right; the templated wording is a small stylistic price for a
guarantee that the number is the number.

The second rule is that no statistic appears above the fold of a card.
*"Pearson r = 0.82"* is true and useless to most people; *"when advertising goes
up, revenue usually goes up too"* is the same fact in a form that can be acted
on. The raw statistic is still there, one click away under **See the numbers**,
so a technical reader can check the claim. Nothing is hidden — it is just not
the first thing you read.

Everything is bounded before it runs: at most twelve numeric columns, one
correlation matrix rather than pairwise loops, and a sample for frames over
50,000 rows (disclosed on the card that used it).

### 5. Draw what was asked for (`core/charts.py`)

An insight card, or an answer from the assistant, can say *"here, look"*. The
tempting way to build that is to let the model emit plotting code and run it.
This does not do that.

Instead the model — or an insight, or a button — emits a **structured spec**: a
small dict naming one of six chart types and some columns. `core/charts.py`
validates every field of it against the DataFrame it will run against, then
renders one of a handful of authored templates. The surface an LLM can reach is
six chart types, column names that already exist, and six aggregation names; it
cannot name a function, a module, or a piece of syntax, and anything outside
that vocabulary is refused with a sentence rather than attempted.

Those charts go through `_glassbox` like every other figure in the app, so a
chart the assistant conjured up ships with the Python that produced it and is no
harder to check than one built at upload time.

### 6. Forecast (`core/ml.py`)

For timeseries only, on request: a `RandomForestRegressor` over `lag_1`,
`lag_7`, `rolling_mean_7`, `day_of_week` and `month`, scored on a chronological
last-20% split, always reported next to a naive "tomorrow looks like today"
baseline.

### 7. Ask about it (`core/chat.py` + `core/tools.py`)

The helper answers questions about the data — which region sells most, whether
revenue is going up, what looks unusual, what this file even is.

**It can never invent a number, and that guarantee is structural rather than a
prompt instruction.** The original rule was that the model sees only computed
summaries: the profile, the routing, the built world's statistics, the forecast
metrics. That rule makes it trustworthy and also makes it unable to answer
"which region sells most?", whose answer is a real number that is in no summary.

The fix is not to relax the rule. It is to put a calculator between the model
and the data:

```
  question → the model PICKS A TOOL from a fixed menu (core/tools.py)
           → the BACKEND runs that tool over the real rows with pandas
           → real numbers come back
           → the model writes the sentence around them
```

Every number in an answer therefore came out of pandas, and the model's
contribution is the English — which is the division of labour each side is
actually good at. `build_context()` and `answer()` still **have no DataFrame
parameter**: the router passes in a `compute` callable, so `core/chat.py` can
ask for a calculation and read the result, and cannot read a row. A missing
function parameter is a stronger guarantee than a filter, because a filter can
be got past.

A plan can contain a tool name from the menu, column names that resolve against
the frame, an aggregation from a whitelist, and an integer that gets clamped.
There is no free-text field anywhere in one, nothing to evaluate, and no way to
name a function. `core/tools.py` validates every plan before running it and
refuses what it cannot resolve, by name.

**Without a key, it still calculates.** A keyword planner reads common phrasings
and produces the *same* computed answer with templated wording. So the assistant
degrades from "understands you" to "understands common phrasings" rather than
from "works" to "unavailable" — and a reply that used the rows carries a quiet
"Worked out from your file" note underneath, because where an answer came from
is part of the answer.

### The two assistants

One chat bubble, two answerers, and a router (`backend/routers/assistant.py`)
that picks between them per message:

| you ask | who answers | what that means |
| --- | --- | --- |
| "which region sold the most?" | `core/chat.py` | picks a calculation, pandas runs it over the real rows, the model writes the sentence around the numbers |
| "what do I do next?" | `core/guide.py` | help about the app: warm, brief, and given the file's shape but never its values |

**Why not one assistant.** The rules that make `core/chat.py` trustworthy make
it useless for onboarding. Asked "what do I do now?", a grounded assistant
correctly observes that no calculation applies and says so — the right answer to
the wrong question, and to a beginner indistinguishable from a broken chatbot.
The reverse is worse: a chatty helper asked "what were total sales?" would
happily produce a plausible number nobody computed. Splitting them means neither
has to be a compromise, and `core/guide.py` inherits the one rule that matters —
it is told the file's name, size and column *names*, never a value, and is
instructed to hand any question about the contents back to the calculator.

**The choice is not a model call.** Classifying with a model would cost a round
trip on every message to decide something two local signals already decide well:
whether `core.tools.plan_from_keywords` recognises a calculation in the
question, and whether the question names one of the dataset's own columns.
Getting it wrong is cheap in both directions — a data question sent to the guide
comes back with "ask me directly and NEXUS will work it out from your rows"; an
app question sent to the calculator falls through to its own summaries path.
Neither fabricates.

`POST /api/assistant` takes an **optional** `session_id`, which is what lets the
same bubble work on the home page. An unknown or expired id is not an error
there either: somebody whose upload has just timed out is exactly the person who
still needs the helper to answer.

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

- **Type:** Inter Tight (display) / Inter (body, tabular figures) / JetBrains
  Mono (code and the small tracked labels that mark a section), on a 1.25
  modular scale from a 16px base. Two faces from one superfamily rather than a
  contrasting pair: the tighter display face makes a headline read as engineered
  instead of as body copy scaled up, while the shared skeleton keeps the page
  cohesive at a glance. Setting the eyebrows in the mono face is the one place
  the typography gets a voice — it says "measurement" without spending a word.
  The one deviation from the ratio is documented in `tokens.css` with its reason.
- **Space:** an 8px scale with a half-step, plus two large steps used only for
  the gaps between screen sections, where "generous" has to read as a pause
  rather than as a margin.
- **Colour: monochrome, and monochrome on purpose.** The product's whole job is
  to show a person what is inside their numbers, so every hue on screen that is
  not carrying meaning is a hue competing with a chart. The interface keeps
  none: surfaces, type and borders are neutral (and *cold* neutral — warm greys
  read editorial, cold greys read instrument), and colour appears only where it
  is a fact — an error, a warning about what had to be done to your data, how
  much of a column is missing, whether the forecast beat its baseline, which way
  a what-if moved, whether the server is answering. A rising trend is
  deliberately **not** coloured green: whether a rise is good news depends on
  what rose, and colouring a climbing PM2.5 reading green would be the app
  cheering at pollution. Nor is the ordinary case coloured — a column with two
  missing values gets a grey bar, because colour spent on "nothing to see here"
  is colour unavailable for the row that matters.
  The chart ramp is achromatic too, separated by *lightness* rather than hue —
  which is the more legible choice here as well as the on-brand one, since a
  ramp with no hue in it is identical for every form of colour-vision
  deficiency. Colour scales that encode a *value* (the correlation heatmap, the
  map) keep their hues, because there the colour is the data.
  Dark mode via `prefers-color-scheme` redefines ~25 role variables, not a
  second stylesheet. **Every pair was measured against WCAG AA 4.5:1.** Colour
  is never the only channel: every type badge prints its type, every null bar
  prints its percentage, and the AI/rules badge says which in words.
- **Motion:** nothing over 260ms, and one orchestrated moment rather than
  scattered effects — the NEXUS mark assembling as a dataset is read, one
  segment per completed backend stage. It cannot run ahead of the work or
  linger after it, because the stage is set from responses rather than a timer.
  `prefers-reduced-motion` collapses durations rather than removing feedback,
  except for the two infinite animations, which are switched off outright
  because at 1ms they would strobe.
- **Semantics:** `header`/`main`/`section`/`article`/`aside`/`footer`, a real
  `<table>` with `<caption>` and `scope`, `<fieldset>`/`<legend>` for the
  segmented controls, `<details>` for disclosures, labelled inputs throughout, a
  skip link, and one global `:focus-visible` ring that nothing is allowed to
  remove.
- **Responsive** to mobile. Each screen is a single centred column, so the
  layout narrows rather than rearranging. The chat bubble becomes a sheet
  pinned to the edges under 560px — not fullscreen, because keeping a strip of
  the page visible is what stops it feeling like a navigation away from the app.
- **The mark** is four nodes at the corners of a square joined by the path
  bottom-left → top-left → bottom-right → top-right. That polyline is the letter
  N; with its vertices drawn it is also a four-node graph. One object, two
  readings, legible at favicon size, and it never needs a second version — the
  logo, the app icon and the loading state are the same glyph.

### The interface, and the one idea it is built around

The visual identity is monochrome and stays monochrome on purpose. The product's
job is to show somebody what is inside their numbers, so every hue on screen
that is not carrying meaning is a hue competing with a chart. Surfaces, type and
borders are neutral; colour appears only where it is a **fact** — something rose,
something fell, something needs attention, a health score. The neutrals are cold
rather than warm, because warm greys read as editorial and cold greys read as
instrument.

**The signature device is the provenance mark.** Every claim carries a small
tracked mono label saying whether pandas produced it, whether AI worded it, or
whether it is an AI inference. It is the visible face of the guarantee at the top
of this README, and it is marked **typographically rather than chromatically** —
deliberately. The obvious move is an "AI colour", a violet or a cyan on anything
the model touched, and it is the move every other product in this category has
already made, so it reads as a genre convention rather than as a claim. A mono
label in the existing greys says the same thing in this app's own voice, and it
keeps colour reserved for what colour means everywhere else here.

**The hero is a specimen, not a screenshot.** The conventional hero for an
analytics product is a picture of its dashboard, and it is the wrong one here:
the claim is not "we draw charts" — everything draws charts — it is "you will be
*told* what is in your file". The characteristic artefact of that claim is a
finding: one sentence, with a number in it, carrying a mark saying where the
number came from. So the home page shows exactly that, at full size, and labels
it as an example — because a fabricated dashboard implying it is the viewer's own
data would be the one dishonest pixel on an otherwise scrupulous page.

**Navigation is text, not icons.** Seven destinations — Story, Charts, Health,
Actions, Rows, Report, Datasets — each named for a question a person actually
arrives with rather than for a capability. There is no "Insights" item, because
"insights" is not a thing anybody wants; there is no "Cleaning" item, because
cleaning is something you do to a health problem and it lives where the problems
are listed. Icons for these would be seven small metaphors to learn, six of them
ambiguous, to narrow a column that is not short of space.

**Numbered markers appear in exactly two places**, and both are genuine
sequences where order is information the reader needs: the four steps on the home
page, and the ranked findings on the story screen, where position one is the most
important thing in the file. Numbering an unordered set of features would be
decoration.

### The loading screen is not theatre

Every stage on the analysis screen **is a request**, marked done when that
request answers. On a small file the stages fly past; on a large one the quality
check visibly sits there, because that is genuinely what is happening.

The alternative — a timed sequence of reassuring messages — is the standard
implementation and it is self-defeating. Anybody who uploads twice sees the same
messages take the same time regardless of the file, and from then on reads every
progress indicator in the product as decoration. See
[`frontend/src/hooks/useAnalysis.js`](frontend/src/hooks/useAnalysis.js).

The same principle drives the work log in Advanced mode: events are recorded in
`core/` and in the routers at the moment work happens, never assembled at render
time from the final state. The gaps between entries are uneven and differ per
dataset, which is the tell that it is a log rather than a stage set.

### Beginner and Advanced

One toggle, two words, no explanation — the change it makes is visible
immediately and reversible instantly, which teaches better than a tooltip would.
Advanced adds the glass-box code panels, the work log, the specific outlier rows,
each issue's score penalty, and defaults explanations to the technical register.
It adds nothing to the navigation and removes nothing from Simple.

The mode is persisted to `localStorage`; the open tab is not. A person who chose
Advanced chose it about *themselves* and expects it to survive a reload; a person
who was last on the Health tab was there about one dataset and expects to land on
the Story when they come back.

### Two places the DOM API is used directly

Both are cases where it is genuinely the better tool, and both are commented in
place:

1. **The upload dropzone** keeps the real `<input type="file">` in the DOM,
   visually hidden but still focusable, with the label as a genuine `<label>`.
   Keyboard and screen-reader behaviour come free, which a `<div>` pretending to
   be a button would have had to reimplement badly.
2. **The assistant panel is `inert` while closed**, so a keyboard user cannot tab
   into a panel that is sliding off screen. It is set from a boolean — an empty
   string would be treated the way the string `"false"` is, as present and
   therefore true, disabling the panel while it is *open*.

### Accessibility and responsiveness, briefly

Every interactive element has a visible focus ring. All animation sits behind
`prefers-reduced-motion`. Colour is never the only carrier of meaning — the score
dial states its number and its grade in text, and comparison arrows are backed by
the direction word in the headline. Wide content (tables, charts, code) scrolls
inside its own container so the page body never scrolls horizontally. Below
900px the rail becomes a horizontal strip and the assistant becomes a sheet with
a scrim; above it, the workspace makes room for the assistant rather than being
covered by it, so you can ask about something that stays visible.

### Bundle

`plotly.js` is assembled from `lib/core` plus only the trace types `core/` can
emit — scatter, bar, box, histogram, heatmap, scattermap — roughly 2.3MB rather
than the 4.9MB default bundle. If a chart type is ever added without registering
its trace, plotly reports "trace type not found" rather than failing silently,
which is the right failure and a one-line fix.

The components from the previous dashboard UI have been **removed** rather than
left unmounted. Keeping fifteen dead files to preserve an interface nobody was
going back to is how a tree becomes unreadable; the git history has them.

## What is tested, and how to run it

```bash
python scripts/test_profiler.py   # semantic types on all samples + small-file cases
python scripts/test_router.py     # live routing + stubbed LLM failure paths
python scripts/test_worlds.py     # all three worlds, degradation, glass-box replay
python scripts/test_ml.py         # forecast honesty, guards, no-leakage split
python scripts/test_api.py        # the FastAPI layer: contracts + serialisation
python scripts/test_chat.py       # the chat assistant cannot fabricate
python scripts/test_intelligence.py  # grounding, health, cleaning, dashboard,
                                     # story, compare
python scripts/test_app.py        # the Streamlit harness, end to end
```

`test_intelligence.py` is the one to read first, because it pins down the two
properties the product is sold on:

- **The grounding check.** Every documented loosening — a sign flip
  (`-20%` written as "a 20% drop"), small integers treated as words, digits
  inside an identifier (`pm25` → "PM2.5") — has a test fixing how far it goes,
  so widening one is a visible change rather than a quiet one. Invented figures
  are asserted to be rejected.
- **"Your original file is preserved."** Asserted directly: the frame handed to
  the cleaner is compared before and after, and the cleaned result is a
  different object.

It runs entirely **without an API key**, which is the point — those modules must
degrade to their rule-based paths, and a suite that only passed with a key would
not be testing the deployment most people run.

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

**There is no notion of a user, so `GET /api/datasets` lists every dataset on
the server.** That is correct for a single-user deployment and would be a data
leak in a shared one. Adding accounts means an owner field on the index record
and a filter in `store.list` — the shape does not have to change for it — but
the absence of that must not be mistaken for the presence of it. Nothing in the
app is authenticated.

**The store is durable but still single-process.** Uploaded bytes and the index
live on disk, so datasets survive a restart and eviction from the in-memory
frame cache loses nothing — the file is simply re-read. What it is not is
horizontally scalable: the parsed frames and the cached analysis live in one
process's memory, so `uvicorn --workers 2` means two workers with two different
analysis caches for the same dataset, and a briefing that changes depending on
which one answers. The production answer is Redis for the metadata and object
storage for the frames; `backend/session.py` keeps its interface narrow
(`create`/`get`/`delete`/`list`) precisely so that swap is a change to one file.

**Three endpoints are no longer driven by the interface.** `/api/world`,
`/api/forecast` and `/api/simulate` predate the autonomous analysis and are not
reachable from any screen in the current UI — the dashboard composes its own
charts, and forecasting is surfaced as a *finding* ("this series is long enough
to project") rather than as a control. They are still implemented, still tested
and still documented, because they are useful to anything driving the API
directly. But they are API surface rather than product surface, and calling them
a feature of the app would be a stretch.

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
