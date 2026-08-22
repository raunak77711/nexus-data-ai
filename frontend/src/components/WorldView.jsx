import { useEffect, useMemo, useRef, useState } from 'react'
import CodePanel from './CodePanel'
import PlotFigure from './PlotFigure'
import WorldStats from './WorldStats'
import './WorldView.css'

/**
 * The world itself: controls, figures, the code behind each figure, and stats.
 *
 * Figure ORDER is fixed by FIGURE_ORDER rather than taken from Object.keys of
 * the response. Object key order happens to be insertion order in practice, but
 * "happens to be" is not something to hang a layout on -- and the main chart
 * must always be first, because it is the answer and everything after it is
 * supporting evidence.
 */

const FIGURE_ORDER = ['main', 'map', 'distribution', 'by_entity', 'correlation']

const FIGURE_TITLES = {
  main: 'Over time',
  map: 'On the map',
  distribution: 'Distribution',
  by_entity: 'By category',
  correlation: 'Correlation',
}

/** How long a control sits still before its value is sent. */
const COMMIT_DELAY_MS = 260

export default function WorldView({
  archetype,
  world,
  params,
  onParamsChange,
  loading,
  error,
  timeBounds,
  anchorRef,
  arrived,
}) {
  const figureCount = Object.keys(world?.figures_json ?? {}).length

  return (
    <section
      className="world"
      aria-labelledby="world-heading"
      aria-busy={loading}
      /* The arrival flourish is a data attribute so the whole thing is one CSS
         rule, and so it costs nothing once it has been removed. */
      data-arrived={arrived ? 'yes' : 'no'}
    >
      <div className="section-title">
        {/* tabIndex -1 makes this focusable programmatically but keeps it out of
            tab order; App moves focus here when the first world lands. */}
        <h2 id="world-heading" ref={anchorRef} tabIndex={-1}>The world</h2>
        {world?.stats?.n_rows_used != null && (
          <span className="section-note tnum">
            built from {world.stats.n_rows_used.toLocaleString()} usable rows
          </span>
        )}
      </div>

      {/* Announced to assistive tech as well as shown: the flourish is visual,
          this is the same information as text. */}
      <p className="world-arrival" role="status" aria-live="polite">
        {arrived && figureCount > 0
          ? `${archetype} world built — ${figureCount} ${figureCount === 1 ? 'figure' : 'figures'}, each with its source.`
          : ''}
      </p>

      <Controls
        archetype={archetype}
        params={params}
        onParamsChange={onParamsChange}
        disabled={loading}
        timeBounds={timeBounds}
      />

      {error && (
        <p className="status-note" data-tone="error">
          <strong>Could not build the world.</strong> {error}
        </p>
      )}

      {loading && <WorldSkeleton />}

      {!loading && !error && world && world.status !== 'ok' && (
        <p className="status-note" data-tone="warning">
          <strong>No world here.</strong> {world.message}
        </p>
      )}

      {!loading && !error && world?.status === 'ok' && (
        <>
          {world.warnings?.length > 0 && (
            <details className="world-warnings">
              <summary>
                <span className="badge world-warning-count">{world.warnings.length}</span>
                What had to be done to your data to plot it
              </summary>
              <ul>
                {world.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}

          <div className="world-figures">
            {orderFigures(world.figures_json).map((name, index) => (
              <article
                key={name}
                className="world-figure panel"
                /* Staggered so the world assembles rather than appearing all at
                   once -- the moment a chart lands is the point of the app. */
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <h3 className="world-figure-title">{FIGURE_TITLES[name] ?? name}</h3>
                <PlotFigure
                  figureJson={world.figures_json[name]}
                  title={FIGURE_TITLES[name] ?? name}
                />
                <CodePanel title={`${name}.py`} code={world.code?.[name]} />
              </article>
            ))}
          </div>

          <WorldStats archetype={archetype} stats={world.stats} />
        </>
      )}
    </section>
  )
}

/** Known figures first, in a fixed reading order; anything unexpected after. */
function orderFigures(figures) {
  const names = Object.keys(figures ?? {})
  const known = FIGURE_ORDER.filter((name) => names.includes(name))
  const rest = names.filter((name) => !FIGURE_ORDER.includes(name))
  return [...known, ...rest]
}

/* ------------------------------------------------------------------ controls */

function Controls({ archetype, params, onParamsChange, disabled, timeBounds }) {
  if (archetype === 'timeseries') {
    return (
      <TimeseriesControls params={params} onParamsChange={onParamsChange} disabled={disabled} />
    )
  }
  if (archetype === 'geo') {
    return (
      <GeoControls
        params={params}
        onParamsChange={onParamsChange}
        disabled={disabled}
        bounds={timeBounds}
      />
    )
  }
  // Tabular has no parameters. Saying so is better than an empty toolbar that
  // looks like something failed to load.
  return (
    <p className="world-controls world-controls-empty">
      The tabular world has no parameters — it shows everything the columns support.
    </p>
  )
}

const FREQUENCIES = [
  { value: 'D', label: 'Daily' },
  { value: 'W', label: 'Weekly' },
  { value: 'M', label: 'Monthly' },
]

function TimeseriesControls({ params, onParamsChange, disabled }) {
  // Local state so the slider label tracks the thumb at 60fps; the commit to
  // the parent (and therefore the network) is debounced below.
  //
  // There is deliberately no effect syncing this back from the prop. The only
  // thing that changes params.rolling_window is this control itself, and a new
  // dataset remounts the whole WorldView (App keys it on the session id), so a
  // sync effect could only ever fight the user's own drag.
  const [window_, setWindow] = useState(params.rolling_window ?? 7)

  useDebouncedCommit(window_, params.rolling_window ?? 7, (value) =>
    onParamsChange({ ...params, rolling_window: value }),
  )

  return (
    <div className="world-controls">
      <fieldset className="control" disabled={disabled}>
        <legend>Resample</legend>
        <div className="segmented">
          {FREQUENCIES.map((option) => (
            <label
              key={option.value}
              className="segmented-option"
              data-selected={(params.freq ?? 'D') === option.value ? 'yes' : 'no'}
            >
              <input
                type="radio"
                name="freq"
                value={option.value}
                checked={(params.freq ?? 'D') === option.value}
                onChange={() => onParamsChange({ ...params, freq: option.value })}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="control control-slider">
        <label htmlFor="rolling-window">
          Rolling mean
          <output htmlFor="rolling-window" className="control-value tnum">
            {window_} {window_ === 1 ? 'period' : 'periods'}
          </output>
        </label>
        <input
          id="rolling-window"
          type="range"
          min="1"
          max="60"
          step="1"
          value={window_}
          disabled={disabled}
          onChange={(event) => setWindow(Number(event.target.value))}
        />
      </div>
    </div>
  )
}

function GeoControls({ params, onParamsChange, disabled, bounds }) {
  // No datetime column means no filter to offer. Hiding the control is better
  // than showing a disabled one the user cannot make sense of.
  if (!bounds) {
    return (
      <p className="world-controls world-controls-empty">
        This dataset has no date column, so there is no time range to filter by.
      </p>
    )
  }

  return <TimeRangeControl params={params} onParamsChange={onParamsChange} disabled={disabled} bounds={bounds} />
}

/**
 * Two range inputs over a shared day axis.
 *
 * WHY two single sliders rather than one dual-handle widget: a dual-handle
 * slider has no native element, so building one means re-implementing pointer
 * capture, keyboard stepping and ARIA from scratch -- a lot of code whose only
 * gain is that the two thumbs share a track. Two labelled `<input type=range>`
 * elements are keyboard-operable and screen-reader-correct by default.
 */
function TimeRangeControl({ params, onParamsChange, disabled, bounds }) {
  const { startMs, endMs, totalDays } = bounds

  const initial = useMemo(() => {
    if (!params.time_filter) return [0, totalDays]
    return params.time_filter.map((iso) =>
      clamp(Math.round((Date.parse(iso) - startMs) / 86_400_000), 0, totalDays),
    )
  }, [params.time_filter, startMs, totalDays])

  const [range, setRange] = useState(initial)

  const commit = (next) => {
    const [from, to] = next
    // Full range means "no filter": sending one would make core/ emit a
    // warning about a filter that excluded nothing.
    if (from === 0 && to === totalDays) {
      onParamsChange({ ...params, time_filter: null })
      return
    }
    onParamsChange({
      ...params,
      time_filter: [isoAtDay(startMs, from), isoAtDay(startMs, to)],
    })
  }

  useDebouncedCommit(range.join(':'), initial.join(':'), () => commit(range))

  const setLow = (value) => setRange(([, high]) => [Math.min(value, high), high])
  const setHigh = (value) => setRange(([low]) => [low, Math.max(value, low)])

  return (
    <div className="world-controls">
      <div className="control control-slider control-range">
        <span className="control-legend">Time range</span>
        <p className="control-value tnum">
          {formatDay(startMs, range[0])} — {formatDay(startMs, range[1])}
        </p>

        <label htmlFor="time-from" className="visually-hidden">Range start</label>
        <input
          id="time-from"
          type="range"
          min="0"
          max={totalDays}
          value={range[0]}
          disabled={disabled}
          onChange={(event) => setLow(Number(event.target.value))}
        />

        <label htmlFor="time-to" className="visually-hidden">Range end</label>
        <input
          id="time-to"
          type="range"
          min="0"
          max={totalDays}
          value={range[1]}
          disabled={disabled}
          onChange={(event) => setHigh(Number(event.target.value))}
        />

        <p className="control-hint tnum">
          {new Date(startMs).toISOString().slice(0, 10)} to{' '}
          {new Date(endMs).toISOString().slice(0, 10)} in the data
        </p>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------- helpers */

/**
 * Call `commit` once the value has stopped changing.
 *
 * A range input fires a change on every pixel of travel. Without this, dragging
 * the rolling-window slider from 7 to 30 would queue twenty-three world builds,
 * each one a pandas resample and a plotly render, and the user would watch the
 * chart flicker through every intermediate value before settling.
 */
function useDebouncedCommit(value, initial, commit) {
  // The callback is captured in a ref, updated in its own effect, so that the
  // timer effect below depends only on the VALUE. Depending on the callback
  // instead would restart the timer on every parent render -- and since the
  // parent re-renders on every keystroke of the slider, the commit would then
  // never fire at all.
  const commitRef = useRef(commit)

  useEffect(() => {
    commitRef.current = commit
  })

  useEffect(() => {
    if (value === initial) return undefined
    const timer = window.setTimeout(() => commitRef.current(value), COMMIT_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [value, initial])
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value))
}

function isoAtDay(startMs, day) {
  return new Date(startMs + day * 86_400_000).toISOString().slice(0, 10)
}

function formatDay(startMs, day) {
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(startMs + day * 86_400_000))
}

/**
 * Placeholder in the shape of the thing that is coming.
 *
 * Two figure-sized blocks, because every archetype produces at least one and
 * most produce two or three -- so the page height barely changes when the real
 * figures replace these, and nothing below jumps.
 */
function WorldSkeleton() {
  return (
    <div className="world-figures" aria-hidden="true">
      {[0, 1].map((index) => (
        <div key={index} className="world-figure panel world-figure-skeleton">
          <div className="skeleton" style={{ height: '18px', width: '30%' }} />
          <div className="skeleton" style={{ height: '360px' }} />
          <div className="skeleton" style={{ height: '36px' }} />
        </div>
      ))}
    </div>
  )
}
