import PlotFigure from './PlotFigure'
import './Overview.css'

/**
 * The first thing you see after a file lands: what is in it, and what NEXUS
 * found in it.
 *
 * Two blocks, in this order and no other. First the SHAPE — rows, columns, and
 * what kinds of column — because a person's first question about a file they
 * just uploaded is "did it read my data properly". Then the FINDINGS, as counts
 * with a way through to each one, because the second question is "so what".
 *
 * The headline chart sits underneath rather than at the top. A chart above the
 * counts would be the app answering a question that has not been asked yet.
 */

export default function Overview({
  filename,
  routing,
  insights,
  insightsLoading,
  world,
  worldLoading,
  onGoToInsights,
  onGoToPredict,
  onGoToExplore,
}) {
  const shape = insights?.shape
  const counts = insights?.counts

  return (
    <div className="overview">
      <header className="screen-head">
        <span className="eyebrow">Dataset</span>
        <h1 className="screen-title">{prettyName(filename)}</h1>
        <p className="lead">{describe(routing, shape)}</p>
      </header>

      <section className="overview-section" aria-labelledby="shape-heading">
        <h2 id="shape-heading" className="section-heading">
          Your data
        </h2>

        {shape ? (
          <dl className="shape-grid">
            <Figure value={shape.n_rows} label={shape.n_rows === 1 ? 'row' : 'rows'} />
            <Figure value={shape.n_cols} label={shape.n_cols === 1 ? 'column' : 'columns'} />
            {shape.n_datetime > 0 && (
              <Figure value={shape.n_datetime} label="date fields" />
            )}
            {shape.n_numeric > 0 && (
              <Figure value={shape.n_numeric} label="number fields" />
            )}
            {shape.n_categorical > 0 && (
              <Figure value={shape.n_categorical} label="category fields" />
            )}
            {shape.n_geo > 0 && <Figure value={shape.n_geo} label="location fields" />}
            {shape.n_text > 0 && <Figure value={shape.n_text} label="text fields" />}
          </dl>
        ) : (
          <div className="skeleton shape-skeleton" />
        )}
      </section>

      <section className="overview-section" aria-labelledby="found-heading">
        <h2 id="found-heading" className="section-heading">
          NEXUS found
        </h2>

        {insightsLoading && <div className="skeleton found-skeleton" />}

        {!insightsLoading && counts && (
          <>
            <ul className="found-list">
              <Found
                n={counts.trends}
                one="thing changing over time"
                many="things changing over time"
                onClick={onGoToInsights}
              />
              <Found
                n={counts.relationships}
                one="pair of columns that move together"
                many="pairs of columns that move together"
                onClick={onGoToInsights}
              />
              <Found
                n={counts.anomalies}
                one="unusual record"
                many="unusual records"
                onClick={onGoToInsights}
              />
              <Found
                n={counts.predictions}
                one="thing worth predicting"
                many="things worth predicting"
                onClick={onGoToPredict}
              />
              <Found
                n={counts.standouts}
                one="group that stands out"
                many="groups that stand out"
                onClick={onGoToInsights}
              />
              <Found
                n={counts.data_issues}
                one="thing to know about the data itself"
                many="things to know about the data itself"
                onClick={onGoToInsights}
              />
            </ul>

            {isEmpty(counts) && (
              <p className="found-none">
                Nothing stood out in this file — no clear trends, no columns moving
                together, nothing unusual. That is a real answer about your data.
              </p>
            )}

            <div className="found-actions">
              <button type="button" className="btn btn-primary" onClick={onGoToInsights}>
                See what NEXUS found
              </button>
              <button type="button" className="btn btn-secondary" onClick={onGoToExplore}>
                Look at the data
              </button>
            </div>
          </>
        )}
      </section>

      <section className="overview-section" aria-labelledby="headline-heading">
        <h2 id="headline-heading" className="section-heading">
          The headline chart
        </h2>
        <p className="section-note">
          Chosen from the shape of your data. Everything else is under Explore.
        </p>

        <div className="overview-figure panel">
          {worldLoading && <div className="skeleton overview-figure-skeleton" />}

          {!worldLoading && world?.status === 'ok' && headlineFigure(world) && (
            <PlotFigure
              figureJson={world.figures_json[headlineFigure(world)]}
              title="Headline chart"
              height={340}
            />
          )}

          {!worldLoading && world && world.status !== 'ok' && (
            <p className="status-note" data-tone="warning">
              <strong>No chart here.</strong> {world.message}
            </p>
          )}
        </div>
      </section>
    </div>
  )
}

/** One big number with a small label. */
function Figure({ value, label }) {
  return (
    <div className="shape-figure">
      <dt className="shape-value tnum">{Number(value).toLocaleString()}</dt>
      <dd className="shape-label">{label}</dd>
    </div>
  )
}

/**
 * One finding count.
 *
 * A count of zero is still rendered, greyed and not clickable. Hiding it would
 * leave the reader unsure whether NEXUS looked and found nothing or never
 * looked — and "we checked, there is nothing" is information.
 */
function Found({ n, one, many, onClick }) {
  const none = !n
  return (
    <li className="found-item" data-empty={none ? 'yes' : 'no'}>
      {none ? (
        <span className="found-line">
          <span className="found-count tnum">0</span>
          <span className="found-text">{many}</span>
        </span>
      ) : (
        <button type="button" className="found-line found-link" onClick={onClick}>
          <span className="found-count tnum">{n.toLocaleString()}</span>
          <span className="found-text">{n === 1 ? one : many}</span>
          <span className="found-go" aria-hidden="true">
            →
          </span>
        </button>
      )}
    </li>
  )
}

/**
 * True only when every pass came back with nothing.
 *
 * Every count is checked, not just the four headline ones. Missing one here
 * would put "nothing stood out" on this screen directly above an Insights
 * screen showing a card, which is the kind of contradiction that costs a
 * product its credibility in one glance.
 */
function isEmpty(counts) {
  return Object.values(counts).every((value) => !value)
}

/** The chart that best represents the dataset, by archetype. */
function headlineFigure(world) {
  const names = Object.keys(world.figures_json ?? {})
  return ['main', 'map', 'distribution', 'by_entity'].find((name) => names.includes(name))
}

/** Strip the extension — the sidebar already shows the filename verbatim. */
function prettyName(filename) {
  return String(filename ?? 'Your dataset').replace(/\.csv$/i, '').replace(/[_-]+/g, ' ')
}

/**
 * A sentence describing the dataset, assembled from the routing decision.
 *
 * Written here rather than asked of the model on purpose: it has to be right
 * every time and cost nothing, and everything in it is already known.
 */
function describe(routing, shape) {
  if (!routing || !shape) return 'Reading your data…'

  const rows = `${shape.n_rows.toLocaleString()} rows`
  const measure = routing.target_col ? friendly(routing.target_col) : null
  const grouped = routing.entity_col ? friendly(routing.entity_col) : null

  if (routing.archetype === 'timeseries' && routing.time_col) {
    return `${rows} of ${measure ?? 'data'} recorded over time${
      grouped ? `, grouped by ${grouped}` : ''
    }. NEXUS has set this up to show change, and can predict what comes next.`
  }
  if (routing.archetype === 'geo') {
    return `${rows} with coordinates, so NEXUS has put ${
      measure ?? 'your measurements'
    } on a map.`
  }
  return `${rows} describing ${measure ?? 'your records'}${
    grouped ? `, grouped by ${grouped}` : ''
  }. NEXUS has set this up for comparing groups and spotting what is related.`
}

function friendly(name) {
  return String(name).replace(/_/g, ' ')
}
