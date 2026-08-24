import { useState } from 'react'
import SpecChart from './SpecChart'
import './Insights.css'

/**
 * What NEXUS found, as things a person can read.
 *
 * The rule for this screen: no statistic appears above the fold of a card. The
 * headline is a sentence about the world ("Revenue is up 85% across this
 * period"), the detail says what that means in the user's own units, and the
 * numbers behind it are one click away under "See the numbers". A reader who
 * wants the correlation coefficient can have it; a reader who does not should
 * never have to scroll past it.
 *
 * Every card that can be SEEN carries a chart spec, and "See why" draws it with
 * the code that produced it attached — so a finding is never something the app
 * merely asserts.
 */

/** What each kind of finding is called, in the user's language. */
const KIND_LABELS = {
  trend: 'Trend',
  relationship: 'Connection',
  anomaly: 'Unusual data',
  segment: 'Standout',
  quality: 'Worth knowing',
  forecast: 'Prediction',
}

export default function Insights({ sessionId, insights, loading, error, onRetry }) {
  if (loading) {
    return (
      <div className="insight-list" aria-busy="true">
        {[0, 1, 2].map((index) => (
          <div key={index} className="skeleton insight-skeleton" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="insight-error">
        <p className="status-note" data-tone="error">
          <strong>The analysis did not finish.</strong> {error}
        </p>
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Try again
        </button>
      </div>
    )
  }

  const cards = insights?.insights ?? []

  if (cards.length === 0) {
    return (
      <div className="insight-empty">
        <h3>Nothing stood out</h3>
        <p>
          NEXUS looked for trends over time, columns that move together, unusual
          records and standout categories, and found none of them in this file.
          That is a real answer about your data, not a failure — steady data with
          no surprises looks exactly like this.
        </p>
      </div>
    )
  }

  return (
    <div className="insight-list">
      {cards.map((card) => (
        <InsightCard key={card.id} card={card} sessionId={sessionId} />
      ))}
    </div>
  )
}

function InsightCard({ card, sessionId }) {
  const [showChart, setShowChart] = useState(false)
  const [showNumbers, setShowNumbers] = useState(false)

  return (
    <article className="insight" data-tone={card.tone}>
      <header className="insight-head">
        <span className="insight-kind eyebrow">{KIND_LABELS[card.kind] ?? card.kind}</span>
        <h3 className="insight-headline">{card.headline}</h3>
      </header>

      <p className="insight-detail">{card.detail}</p>

      <div className="insight-why">
        <span className="eyebrow">Why it matters</span>
        <p>{card.why}</p>
      </div>

      <div className="insight-actions">
        {card.action && (
          <button
            type="button"
            className="btn btn-secondary insight-btn"
            onClick={() => setShowChart((open) => !open)}
            aria-expanded={showChart}
          >
            {showChart ? 'Hide chart' : 'See why →'}
          </button>
        )}

        <button
          type="button"
          className="btn btn-ghost insight-btn"
          onClick={() => setShowNumbers((open) => !open)}
          aria-expanded={showNumbers}
        >
          {showNumbers ? 'Hide the numbers' : 'See the numbers'}
        </button>
      </div>

      {showChart && card.action && (
        <div className="insight-chart">
          <SpecChart sessionId={sessionId} spec={card.action} height={300} />
        </div>
      )}

      {showNumbers && (
        <dl className="insight-evidence">
          {flatten(card.evidence).map(([label, value]) => (
            <div key={label} className="insight-evidence-row">
              <dt>{label}</dt>
              <dd className="tnum">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  )
}

/**
 * Turn an evidence dict into label/value pairs a person can read.
 *
 * The evidence is whatever the analysis pass computed, so it is nested and its
 * keys are written for a program. Flattening one level and humanising the keys
 * is enough: two levels deep, the labels get long enough that a table stops
 * being easier to read than the sentence above it.
 */
function flatten(evidence, prefix = '') {
  const rows = []
  for (const [key, value] of Object.entries(evidence ?? {})) {
    const label = humanise(prefix ? `${prefix} ${key}` : key)
    if (value === null || value === undefined) continue

    if (Array.isArray(value)) {
      rows.push([label, value.map(format).join(' – ')])
    } else if (typeof value === 'object') {
      rows.push(...flatten(value, key))
    } else {
      rows.push([label, format(value)])
    }
  }
  return rows
}

function humanise(key) {
  const text = String(key).replace(/_/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function format(value) {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, {
      maximumFractionDigits: 3,
    })
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}
