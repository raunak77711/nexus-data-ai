import { useEffect, useState } from 'react'
import * as api from '../api'
import CodePanel from './CodePanel'
import PlotFigure from './PlotFigure'
import './SpecChart.css'

/**
 * A chart built from a structured spec, on demand.
 *
 * This is the component behind "See why →" on an insight and behind a chart the
 * assistant produces. It takes a spec — `{ chart: 'bar', x: 'region', y:
 * 'revenue', agg: 'sum' }` — posts it, and renders what comes back.
 *
 * WHY THE SPEC IS SENT TO THE SERVER RATHER THAN DRAWN HERE: the figure is
 * built by the same code path as every other figure in the app, so it arrives
 * with the Python that produced it attached. A chart the assistant conjured up
 * is therefore no harder to check than one the app built at upload time — which
 * is the whole argument the product makes. Drawing it in the browser would have
 * been less code and would have quietly broken that promise.
 *
 * This is also the one component that fetches. Everywhere else, App owns the
 * network — but a spec chart is created and destroyed by the user opening and
 * closing a disclosure, and hoisting a dozen of those into App would mean App
 * holding a cache keyed by a spec nobody else reads.
 */
export default function SpecChart({ sessionId, spec, showCode = true, height }) {
  const [state, setState] = useState({ status: 'loading' })

  // The spec is an object literal at most call sites, so it would be a new
  // reference on every render and the effect would re-fetch forever. Serialising
  // it gives a stable dependency that changes exactly when the request would.
  const specKey = JSON.stringify(spec ?? null)

  useEffect(() => {
    if (!sessionId || !spec) return undefined
    let cancelled = false

    // oxlint-disable-next-line react/set-state-in-effect -- fetch effect: the
    // loading flag has to be raised in the same tick the request leaves.
    setState({ status: 'loading' })
    api
      .buildChart(sessionId, spec)
      .then((payload) => {
        if (!cancelled) setState({ status: 'ready', payload })
      })
      .catch((error) => {
        if (!cancelled) setState({ status: 'error', message: error.message })
      })

    return () => {
      cancelled = true
    }
    // `spec` itself is deliberately not a dependency -- specKey stands for it,
    // and listing both would reintroduce the identity problem specKey solves.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, specKey])

  if (state.status === 'loading') {
    return <div className="spec-chart-loading skeleton" style={{ height: height ?? 320 }} />
  }

  if (state.status === 'error') {
    return (
      <p className="status-note" data-tone="warning">
        <strong>That chart could not be drawn.</strong> {state.message}
      </p>
    )
  }

  const { payload } = state

  return (
    <figure className="spec-chart">
      <PlotFigure figureJson={payload.figure_json} title={payload.title} height={height} />

      {payload.warnings?.length > 0 && (
        <figcaption className="spec-chart-note">{payload.warnings.join(' ')}</figcaption>
      )}

      {showCode && <CodePanel title="how this was calculated" code={payload.code} />}
    </figure>
  )
}
