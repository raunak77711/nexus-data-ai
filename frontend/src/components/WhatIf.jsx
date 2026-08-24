import { useState } from 'react'
import './WhatIf.css'

/**
 * What if this number moved?
 *
 * The panel is small because the honest version of this feature is small. It
 * can do two things — scale a measure directly, or project one measure from
 * another using the straight line that fits their history — and it says which
 * one it did, every time, above the number.
 *
 * The caveats are rendered next to the result rather than behind a tooltip.
 * That is the whole design decision here: a projection whose assumptions are
 * hidden is a projection being passed off as a measurement, and this app spends
 * its credibility elsewhere.
 */

/** Preset steps. A free-text percentage invites 1000% and answers it. */
const STEPS = [-20, -10, 10, 20, 50]

export default function WhatIf({ options, result, loading, error, onRun, onReset }) {
  const [pct, setPct] = useState(20)
  // null means "the user has not chosen"; '' means they chose the direct case.
  // Distinguishing the two is what lets the default below apply exactly once,
  // without an effect that would fight the user's own selection afterwards.
  const [chosenDriver, setChosenDriver] = useState(null)

  // Derived, not synced. Until the user picks something, prefer a driver that
  // actually moves with the target: a what-if through a real relationship is
  // the interesting case, and defaulting to the arithmetic one would hide that
  // this app can do better than arithmetic.
  const driver = chosenDriver ?? options?.suggested_driver ?? ''

  if (!options) return <div className="skeleton whatif-skeleton" />

  if (!options.available) {
    return (
      <div className="whatif-empty">
        <h3>Nothing to simulate here</h3>
        <p>
          A what-if needs a numeric measure to move. This dataset does not have
          one that would mean anything on a slider.
        </p>
      </div>
    )
  }

  const target = options.default_target
  const movable = driver || target

  return (
    <div className="whatif">
      <div className="whatif-controls">
        <div className="whatif-field">
          <label className="eyebrow" htmlFor="whatif-driver">
            Change
          </label>
          <select
            id="whatif-driver"
            className="whatif-select"
            value={driver}
            onChange={(event) => {
              setChosenDriver(event.target.value)
              onReset()
            }}
          >
            <option value="">{friendly(target)} directly</option>
            {options.columns
              .filter((name) => name !== target)
              .map((name) => (
                <option key={name} value={name}>
                  {friendly(name)}
                </option>
              ))}
          </select>
        </div>

        <div className="whatif-field">
          <span className="eyebrow" id="whatif-amount-label">
            By
          </span>
          <div
            className="whatif-steps"
            role="group"
            aria-labelledby="whatif-amount-label"
          >
            {STEPS.map((step) => (
              <button
                key={step}
                type="button"
                className="whatif-step"
                data-selected={pct === step ? 'yes' : 'no'}
                aria-pressed={pct === step}
                onClick={() => setPct(step)}
              >
                {step > 0 ? `+${step}%` : `${step}%`}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          className="btn btn-primary whatif-run"
          onClick={() => onRun({ pctChange: pct, driver: driver || null, target })}
          disabled={loading}
        >
          {loading ? 'Working it out…' : 'Show me'}
        </button>
      </div>

      <p className="whatif-question">
        {movable === target ? (
          <>
            What if <strong>{friendly(target)}</strong>{' '}
            {pct >= 0 ? 'went up' : 'went down'} <strong>{Math.abs(pct)}%</strong>?
          </>
        ) : (
          <>
            What happens to <strong>{friendly(target)}</strong> if{' '}
            <strong>{friendly(movable)}</strong>{' '}
            {pct >= 0 ? 'goes up' : 'goes down'} <strong>{Math.abs(pct)}%</strong>?
          </>
        )}
      </p>

      {error && (
        <p className="status-note" data-tone="error">
          <strong>That did not work.</strong> {error}
        </p>
      )}

      {result?.status === 'unsupported' && (
        <div className="whatif-refused">
          <span className="eyebrow">Not answerable</span>
          <p>{result.message}</p>
          {result.caveats?.map((caveat) => (
            <p key={caveat} className="whatif-caveat">
              {caveat}
            </p>
          ))}
        </div>
      )}

      {result?.status === 'ok' && (
        <div className="whatif-result rise-in">
          <span className="eyebrow">
            {result.basis === 'relationship'
              ? 'Estimated from how these two have moved together'
              : 'Straight arithmetic on your own numbers'}
          </span>

          <div className="whatif-numbers">
            <div className="whatif-number">
              <span className="whatif-number-label">Today</span>
              <span className="whatif-number-value tnum">
                {format(result.baseline.total)}
              </span>
            </div>

            <span className="whatif-arrow" aria-hidden="true">
              →
            </span>

            <div className="whatif-number whatif-number-lead">
              <span className="whatif-number-label">Projected</span>
              <span className="whatif-number-value tnum">
                {format(result.projected.total)}
              </span>
            </div>
          </div>

          {/* The change is its own line rather than tucked under one of the two
              figures: hanging it off "Projected" made the two numbers sit at
              different heights, and the change describes the pair, not one of
              them. */}
          <p
            className="whatif-delta tnum"
            data-direction={result.delta.total >= 0 ? 'up' : 'down'}
          >
            {result.delta.total >= 0 ? '+' : '−'}
            {format(Math.abs(result.delta.total))} ({result.delta.pct >= 0 ? '+' : ''}
            {result.delta.pct}%)
          </p>

          <p className="whatif-message">{result.message}</p>

          <ul className="whatif-caveats">
            {result.caveats?.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function friendly(name) {
  return String(name ?? '').replace(/_/g, ' ')
}

function format(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number.toLocaleString(undefined, { maximumFractionDigits: 0 })
}
