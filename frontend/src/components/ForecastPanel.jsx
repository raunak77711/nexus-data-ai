import { useMemo, useState } from 'react'
import CodePanel from './CodePanel'
import PlotFigure from './PlotFigure'
import './ForecastPanel.css'

/**
 * Forecast: predictions against actuals, both MAEs, and an unhidden verdict.
 *
 * THE DESIGN RULE THIS PANEL EXISTS TO ENFORCE: a loss is displayed exactly as
 * prominently as a win. Every part of the layout is symmetric between the two
 * outcomes -- the same card, the same size, the same position -- and only the
 * colour changes: green when the model beats the naive baseline, amber when it
 * does not.
 *
 * WHY that matters more than it might sound: the naive "tomorrow equals today"
 * baseline is genuinely hard to beat on real series, so a model that loses is
 * the common case, not the failure case. An interface that shrinks or hides the
 * losing verdict would be tuning the presentation until the model looks good,
 * which is the same sin as tuning the benchmark until it wins. Amber rather
 * than red for the same reason as the routing banner: losing to the baseline is
 * a legitimate, informative result, not a bug.
 *
 * The two MAEs sit side by side, at the same type size, because a MAE quoted
 * alone is unreadable -- 4.2 means nothing until you know what predicting
 * yesterday's value would have scored.
 */

const HORIZONS = [7, 14, 30]

export default function ForecastPanel({ forecast, loading, error, onRun, horizon, onHorizonChange }) {
  const [expanded, setExpanded] = useState(false)

  const chart = useMemo(() => buildChart(forecast), [forecast])

  return (
    <section className="forecast" aria-labelledby="forecast-heading">
      <div className="section-title">
        <h2 id="forecast-heading">Predict what is next</h2>
        <span className="section-note">
          NEXUS learns from your history, then checks itself against the simplest
          possible guess — that tomorrow looks like today.
        </span>
      </div>

      <div className="forecast-controls">
        <fieldset className="control" disabled={loading}>
          <legend>Horizon</legend>
          <div className="segmented">
            {HORIZONS.map((days) => (
              <label
                key={days}
                className="segmented-option"
                data-selected={horizon === days ? 'yes' : 'no'}
              >
                <input
                  type="radio"
                  name="horizon"
                  value={days}
                  checked={horizon === days}
                  onChange={() => onHorizonChange(days)}
                />
                <span>{days} days</span>
              </label>
            ))}
          </div>
        </fieldset>

        <button type="button" className="btn btn-primary" onClick={onRun} disabled={loading}>
          {loading ? 'Fitting…' : forecast ? 'Refit' : 'Run the forecast'}
        </button>
      </div>

      {error && (
        <p className="status-note" data-tone="error">
          <strong>The forecast failed.</strong> {error}
        </p>
      )}

      {loading && (
        <div className="panel forecast-skeleton" aria-hidden="true">
          <div className="skeleton" style={{ height: '76px' }} />
          <div className="skeleton" style={{ height: '300px' }} />
        </div>
      )}

      {!loading && forecast && forecast.status !== 'ok' && (
        <p className="status-note" data-tone="warning">
          <strong>No forecast for this dataset.</strong> {forecast.message}
        </p>
      )}

      {!loading && forecast?.status === 'ok' && (
        <div className="forecast-body">
          {/* --------------------------------------------------- verdict -- */}
          <article
            className="verdict panel"
            data-outcome={forecast.beats_baseline ? 'win' : 'loss'}
          >
            <header className="verdict-head">
              <span className="badge verdict-badge">
                {forecast.beats_baseline ? 'Beats the baseline' : 'Loses to the baseline'}
              </span>
              {forecast.metrics.improvement_pct != null && (
                <span className="verdict-delta tnum">
                  {forecast.metrics.improvement_pct > 0 ? '+' : ''}
                  {forecast.metrics.improvement_pct.toFixed(1)}%
                </span>
              )}
            </header>

            <p className="verdict-text">{forecast.verdict}</p>

            <div className="mae-pair">
              <div className="mae" data-role="model">
                <span className="mae-label">Model MAE</span>
                <span className="mae-value tnum">{format(forecast.metrics.test_mae)}</span>
              </div>
              <span className="mae-vs" aria-hidden="true">vs</span>
              <div className="mae" data-role="baseline">
                <span className="mae-label">Baseline MAE</span>
                <span className="mae-value tnum">{format(forecast.metrics.baseline_mae)}</span>
                <span className="mae-note">predict yesterday</span>
              </div>
            </div>

            <dl className="verdict-meta">
              <div><dt>Train</dt><dd className="tnum">{forecast.metrics.n_train} days</dd></div>
              <div><dt>Test</dt><dd className="tnum">{forecast.metrics.n_test} days</dd></div>
              <div>
                <dt>Forward-filled</dt>
                <dd className="tnum">{forecast.metrics.filled_pct}%</dd>
              </div>
            </dl>
          </article>

          {forecast.warnings?.length > 0 && (
            <details
              className="forecast-caveats"
              open={expanded}
              onToggle={(event) => setExpanded(event.currentTarget.open)}
            >
              <summary>
                <span className="badge forecast-caveat-count">{forecast.warnings.length}</span>
                Caveats that change how this should be read
              </summary>
              <ul>
                {forecast.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}

          {/* ----------------------------------------------------- chart -- */}
          {chart && (
            <article className="panel forecast-chart">
              <h3>Predicted against actual</h3>
              <p className="section-note">
                The shaded window past the last observation is the projection; errors
                compound across it, because each predicted day becomes the next day's
                input.
              </p>
              <PlotFigure figure={chart} title="Predicted against actual" />
            </article>
          )}

          {/* ------------------------------------------------ importances -- */}
          <FeatureImportances importances={forecast.feature_importances} />

          <CodePanel title="forecast.py" code={forecast.code} />
        </div>
      )}
    </section>
  )
}

/**
 * Build the actual-vs-predicted chart from the two record arrays.
 *
 * Composed here rather than sent as a server figure because the shape of this
 * chart is a presentation decision (where the projection starts, how the two
 * windows are visually separated), and core.ml's job is to return numbers, not
 * to decide what a projection should look like.
 */
function buildChart(forecast) {
  if (forecast?.status !== 'ok' || !forecast.predictions?.length) return null

  const dates = forecast.predictions.map((row) => row.date)
  const actual = forecast.predictions.map((row) => row.actual)
  const predicted = forecast.predictions.map((row) => row.predicted)
  const futureDates = (forecast.future ?? []).map((row) => row.date)
  const futureValues = (forecast.future ?? []).map((row) => row.predicted)

  const traces = [
    {
      x: dates,
      y: actual,
      type: 'scatter',
      mode: 'lines',
      name: 'Actual',
      line: { width: 2, color: '#5c6172' },
    },
    {
      x: dates,
      y: predicted,
      type: 'scatter',
      mode: 'lines',
      name: 'Predicted (held-out test)',
      line: { width: 2, color: '#6350f5', dash: 'dot' },
    },
  ]

  if (futureDates.length) {
    // The projection is joined to the last test point so the line is continuous
    // rather than floating detached to the right of the chart.
    traces.push({
      x: [dates.at(-1), ...futureDates],
      y: [predicted.at(-1), ...futureValues],
      type: 'scatter',
      mode: 'lines',
      name: 'Projection',
      line: { width: 2, color: '#ff6b3d' },
    })
  }

  return {
    data: traces,
    layout: {
      hovermode: 'x unified',
      // A band behind the projection, so "past the data" is visible without
      // having to read the legend.
      shapes: futureDates.length
        ? [
            {
              type: 'rect',
              xref: 'x',
              yref: 'paper',
              x0: dates.at(-1),
              x1: futureDates.at(-1),
              y0: 0,
              y1: 1,
              fillcolor: 'rgba(255, 107, 61, 0.07)',
              line: { width: 0 },
              layer: 'below',
            },
          ]
        : [],
    },
  }
}

/**
 * Feature importances as CSS bars rather than a chart.
 *
 * Five values with names is a list, not a plot. A bar chart here would cost a
 * plotly instance, an axis, a margin and 300px of vertical space to say what
 * five rows of text and a coloured rule say more compactly -- and the bars stay
 * readable at tablet width, which a five-category horizontal bar chart does not.
 */
function FeatureImportances({ importances }) {
  const entries = Object.entries(importances ?? {})
  if (entries.length === 0) return null

  const max = Math.max(...entries.map(([, value]) => value)) || 1

  return (
    <article className="panel importances">
      <h3>What the model leaned on</h3>
      <p className="section-note">
        Gini importance from the fitted forest — which inputs it split on, not
        which inputs are causal.
      </p>
      <ul className="importance-list">
        {entries.map(([name, value], index) => (
          <li key={name} className="importance">
            <span className="importance-name">{name}</span>
            <span className="importance-track">
              <span
                className="importance-fill"
                style={{
                  width: `${(value / max) * 100}%`,
                  animationDelay: `${index * 50}ms`,
                }}
              />
            </span>
            <span className="importance-value tnum">{(value * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </article>
  )
}

function format(value) {
  if (value == null) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 })
}
