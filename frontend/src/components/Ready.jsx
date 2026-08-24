import PlotFigure from './PlotFigure'
import './Ready.css'

/**
 * Everything after a successful upload, on ONE scrolling page.
 *
 * WHAT THIS REPLACED. There used to be a sidebar with four destinations —
 * Overview, Explore, Insights, Predict — plus an archetype selector, a routing
 * banner, a column profile table, a rows preview, frequency and rolling-window
 * sliders, a forecast horizon control, a what-if simulator and a code panel
 * under every chart. All of it works. Almost none of it answers the question a
 * person actually has thirty seconds after uploading a file, which is: did that
 * work, and what do I do now?
 *
 * So the page answers exactly that, in the order it gets asked:
 *
 *   1. DID IT WORK          a green tick, the file's name, its size in rows
 *   2. WHAT DID YOU DO      three past-tense lines, no jargon
 *   3. WHAT DO I DO NOW     one primary action, and one way back
 *   4. ...and then the actual results, for anyone who scrolls.
 *
 * Nothing here is a control. There is no setting to choose, no chart type to
 * pick, no parameter to tune — because every one of those is a decision handed
 * to somebody who came here to be told something, and a decision they cannot
 * make is a decision that stops them.
 *
 * WHAT WAS NOT THROWN AWAY. The findings and the chart are the substance and
 * they are all still here; the forecast section appears only when the dataset
 * genuinely supports one. What went is the machinery around them.
 */

/** How many findings to show. Beyond about four this becomes a list to skim. */
const MAX_FINDINGS = 4

/** Figures come back keyed by role; this is the one worth showing on its own. */
const HEADLINE_FIGURES = ['main', 'map', 'distribution', 'by_entity']

export default function Ready({
  session,
  world,
  worldLoading,
  worldError,
  insights,
  insightsLoading,
  forecast,
  forecastLoading,
  canForecast,
  onRunForecast,
  onAskHelper,
  onStartOver,
}) {
  const rows = session.n_rows
  const columns = session.n_cols
  const findings = (insights?.insights ?? []).slice(0, MAX_FINDINGS)
  const headlineFigure = pickFigure(world?.figures_json)

  return (
    <div className="ready">
      {/* ---------------------------------------------------- 1. did it work */}
      {/* role="status" so a screen reader hears the outcome without having to
          go looking for it — the confirmation appears where focus is not. */}
      <section className="done" role="status">
        <span className="done-tick" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="m4 12.5 5.5 5.5L20 7" />
          </svg>
        </span>

        <div className="done-text">
          <h1 className="done-title">Your file is ready</h1>
          <p className="done-file">
            <strong>{session.filename}</strong>
            <span className="done-meta tnum">
              {formatCount(rows)} {rows === 1 ? 'row' : 'rows'} ·{' '}
              {formatCount(columns)} {columns === 1 ? 'column' : 'columns'}
            </span>
          </p>
        </div>
      </section>

      {/* -------------------------------------------------- 2. what we did */}
      <section className="did" aria-labelledby="did-heading">
        <h2 id="did-heading" className="ready-heading">
          Here is what we did
        </h2>
        <ul className="did-list">
          <Did done>
            Opened your file and read all {formatCount(rows)}{' '}
            {rows === 1 ? 'row' : 'rows'}
          </Did>
          <Did done>
            Checked each of the {formatCount(columns)}{' '}
            {columns === 1 ? 'column' : 'columns'} to see what it holds
          </Did>
          <Did done={!worldLoading} pending={worldLoading}>
            {worldLoading ? 'Drawing a chart of the main thing in it' : 'Drew a chart of the main thing in it'}
          </Did>
          <Did done={!insightsLoading} pending={insightsLoading}>
            {insightsLoading
              ? 'Looking for anything worth pointing out'
              : describeFound(insights)}
          </Did>
        </ul>
      </section>

      {/* ------------------------------------------------- 3. what now */}
      <section className="next" aria-labelledby="next-heading">
        <h2 id="next-heading" className="ready-heading">
          What now?
        </h2>
        <p className="next-lead">
          Ask a question about your file in plain English. Every answer is worked
          out from your own rows.
        </p>

        <div className="next-actions">
          <button type="button" className="btn btn-primary" onClick={onAskHelper}>
            Ask a question
          </button>
          <button type="button" className="btn btn-ghost" onClick={onStartOver}>
            Use a different file
          </button>
        </div>
      </section>

      {/* ------------------------------------------------------ the chart */}
      <section className="ready-block" aria-labelledby="chart-heading">
        <h2 id="chart-heading" className="ready-heading">
          Your data as a picture
        </h2>

        {worldLoading && <div className="skeleton ready-skeleton" />}

        {!worldLoading && headlineFigure && (
          <div className="ready-chart">
            <PlotFigure figureJson={headlineFigure} title="Your data" height={320} />
          </div>
        )}

        {/* A failed chart is one missing panel, not a broken page — and saying
            so plainly is better than an empty space the user has to interpret. */}
        {!worldLoading && !headlineFigure && (
          <p className="ready-quiet">
            {worldError
              ? 'We could not draw a chart for this file, but everything else below still works.'
              : 'There was not a clear chart to draw from this file.'}
          </p>
        )}
      </section>

      {/* --------------------------------------------------- the findings */}
      <section className="ready-block" aria-labelledby="found-heading">
        <h2 id="found-heading" className="ready-heading">
          What we noticed
        </h2>

        {insightsLoading && (
          <div className="finding-list" aria-busy="true">
            {[0, 1, 2].map((index) => (
              <div key={index} className="skeleton finding-skeleton" />
            ))}
          </div>
        )}

        {!insightsLoading && findings.length > 0 && (
          <ul className="finding-list">
            {findings.map((finding) => (
              <li key={finding.id} className="finding" data-tone={finding.tone}>
                <p className="finding-headline">{finding.headline}</p>
                <p className="finding-detail">{finding.detail}</p>
              </li>
            ))}
          </ul>
        )}

        {!insightsLoading && findings.length === 0 && (
          <p className="ready-quiet">
            Nothing in this file stood out as unusual. That is a normal result,
            and often a good one.
          </p>
        )}
      </section>

      {/* ---------------------------------------------------- the forecast --
          Shown ONLY when the data genuinely supports one. The old version had
          a whole screen for this that explained, to every user of every file,
          why their file could not be forecast. An empty room you have to be
          told about is worse than no room. */}
      {canForecast && (
        <section className="ready-block" aria-labelledby="ahead-heading">
          <h2 id="ahead-heading" className="ready-heading">
            What might happen next
          </h2>

          {!forecast && !forecastLoading && (
            <div className="ahead-offer">
              <p className="ready-quiet">
                This file has dates and a number measured over them, so we can
                estimate where it is heading.
              </p>
              <button type="button" className="btn btn-secondary" onClick={onRunForecast}>
                Work it out
              </button>
            </div>
          )}

          {forecastLoading && <div className="skeleton ready-skeleton" />}

          {forecast && !forecastLoading && (
            <div className="ahead-result">
              <p className="ahead-verdict">{forecast.message}</p>
              {/* `verdict` is the honest part: the model is scored against a
                  naive baseline it is allowed to lose to, and when it loses the
                  page says so. That sentence stays even on the simple screen —
                  it is the difference between a prediction and a guess. */}
              <p className="ready-quiet">{forecast.verdict}</p>
            </div>
          )}
        </section>
      )}

      <footer className="ready-foot">
        <p className="ready-quiet">
          Your file is kept for one hour so you can ask questions about it, then
          it is deleted. It is not shared with anyone.
        </p>
      </footer>
    </div>
  )
}

/** One line in "here is what we did": a tick, a spinner, and a sentence. */
function Did({ children, done, pending }) {
  return (
    <li className="did-item" data-state={pending ? 'pending' : done ? 'done' : 'waiting'}>
      <span className="did-mark" aria-hidden="true">
        {pending ? (
          <span className="did-spinner" />
        ) : (
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
               strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="m4 12.5 5.5 5.5L20 7" />
          </svg>
        )}
      </span>
      <span className="did-label">{children}</span>
    </li>
  )
}

/**
 * The fourth "what we did" line, once the analysis is in.
 *
 * Counting the findings rather than naming their types: "found 6 things worth
 * pointing out" is a sentence anybody can read, where "3 trends, 2 correlations
 * and an anomaly" asks the reader to know what those are.
 */
function describeFound(insights) {
  const total = (insights?.insights ?? []).length
  if (!insights) return 'Looked through it for anything worth pointing out'
  if (total === 0) return 'Looked it over — nothing unusual to flag'
  return `Found ${total} ${total === 1 ? 'thing' : 'things'} worth pointing out`
}

/** The single most representative figure this world produced, if any. */
function pickFigure(figures) {
  if (!figures) return null
  const name = HEADLINE_FIGURES.find((key) => figures[key]) ?? Object.keys(figures)[0]
  return name ? figures[name] : null
}

/** Thousands separators, so 14000 rows does not read as 14 rows at a glance. */
function formatCount(value) {
  return typeof value === 'number' ? value.toLocaleString() : String(value ?? '')
}
