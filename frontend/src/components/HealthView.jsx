import { useCallback, useMemo, useState } from 'react'
import * as api from '../api'
import ExplainThis from './ExplainThis'
import Provenance from './Provenance'
import ScoreDial from './ScoreDial'
import './HealthView.css'

/**
 * The data health report, and the cleaning flow that acts on it.
 *
 * THE CONSENT MODEL IS THE DESIGN
 * -------------------------------
 * The product's promise is that data is never changed without review. That
 * promise is made or broken by this screen, so the flow is deliberately three
 * steps and the middle one cannot be skipped:
 *
 *   1. every issue, with what it is and why it matters
 *   2. tick the ones to fix, then see the exact operations that would run
 *   3. apply — and the original file is still there afterwards
 *
 * A single "Clean my data" button would be one click and would be the wrong
 * product. Somebody approving a clean is agreeing to specific operations on
 * specific columns, and they cannot agree to what they have not seen.
 *
 * WHY EVERY FIXABLE ISSUE STARTS TICKED. The default has to be one or the
 * other and neither is neutral. Starting unticked means the common case —
 * "yes, fix the obvious problems" — costs eight clicks; starting ticked means
 * the user reviews a proposal rather than assembling one, which is the easier
 * cognitive task and the one the plan step exists to support. Nothing is
 * applied until the button is pressed either way.
 */
export default function HealthView({ sessionId, health, mode, onCleaned, onReverted }) {
  const fixable = useMemo(
    () => (health?.issues ?? []).filter((issue) => issue.fix),
    [health],
  )

  const [selected, setSelected] = useState(() => new Set(fixable.map((i) => i.id)))
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState(null)

  const toggle = useCallback((id) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    // A changed selection invalidates the plan it produced. Leaving a stale
    // plan on screen next to a different set of ticks is how somebody approves
    // one thing believing it is another.
    setPlan(null)
  }, [])

  const review = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setPlan(await api.planClean(sessionId, [...selected]))
    } catch (caught) {
      setError(caught.message)
    } finally {
      setBusy(false)
    }
  }, [sessionId, selected])

  const apply = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.applyClean(sessionId, [...selected])
      setReceipt(result)
      setPlan(null)
      onCleaned?.(result)
    } catch (caught) {
      setError(caught.message)
    } finally {
      setBusy(false)
    }
  }, [sessionId, selected, onCleaned])

  const revert = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.revertClean(sessionId)
      setReceipt(null)
      setPlan(null)
      onReverted?.(result)
    } catch (caught) {
      setError(caught.message)
    } finally {
      setBusy(false)
    }
  }, [sessionId, onReverted])

  if (!health) {
    return <p className="health__loading">Checking your data…</p>
  }

  const issues = health.issues ?? []
  const clean = health.clean ?? []

  return (
    <div className="health">
      {/* ---------------------------------------------------------- score -- */}
      <header className="health__head">
        <ScoreDial score={health.score ?? 0} size={88} />
        <div className="health__head-text">
          <p className="health__eyebrow">Data health</p>
          <h1 className="health__grade">{health.grade}</h1>
          <p className="health__verdict">{health.verdict}</p>
          <p className="health__headline">{health.headline}</p>
          {health.sampled && (
            <p className="health__sampled">
              This file is large, so the checks ran on a random sample of it. The
              proportions are reliable; the exact counts are estimates.
            </p>
          )}
        </div>
      </header>

      {/* -------------------------------------------------------- receipt -- */}
      {receipt && (
        <section className="health__receipt">
          <h2 className="health__receipt-title">What changed</h2>
          <p className="health__receipt-summary">{receipt.summary}</p>
          <ul className="health__receipt-log">
            {receipt.log.map((entry, index) => (
              <li key={`${entry.action}-${index}`}>{entry.summary}</li>
            ))}
          </ul>
          <div className="health__receipt-actions">
            <button type="button" className="button button--quiet" onClick={revert} disabled={busy}>
              Undo — go back to my original file
            </button>
            <a className="button button--quiet" href={api.exportUrl(sessionId)} download>
              Download the cleaned CSV
            </a>
          </div>
          <Provenance kind="computed" />
        </section>
      )}

      {/* --------------------------------------------------------- issues -- */}
      {issues.length > 0 ? (
        <section className="health__issues">
          <div className="health__issues-head">
            <h2 className="health__section-title">
              {issues.length} thing{issues.length === 1 ? '' : 's'} to know about
            </h2>
            {fixable.length > 0 && (
              <p className="health__issues-note">
                {fixable.length} can be repaired automatically. Tick what you
                want fixed, then review the exact changes before anything
                happens.
              </p>
            )}
          </div>

          <ul className="health__list">
            {issues.map((issue) => (
              <li key={issue.id} className="issue" data-severity={issue.severity}>
                <div className="issue__row">
                  {issue.fix ? (
                    <label className="issue__check">
                      <input
                        type="checkbox"
                        checked={selected.has(issue.id)}
                        onChange={() => toggle(issue.id)}
                      />
                      <span className="issue__check-box" aria-hidden="true" />
                      <span className="sr-only">Fix: {issue.title}</span>
                    </label>
                  ) : (
                    <span
                      className="issue__check issue__check--none"
                      title="This one needs a human decision — it cannot be repaired automatically."
                      aria-hidden="true"
                    />
                  )}

                  <div className="issue__body">
                    <div className="issue__heading">
                      <span className="issue__severity">{issue.severity}</span>
                      <h3 className="issue__title">{issue.title}</h3>
                    </div>
                    <p className="issue__detail">{issue.detail}</p>
                    <p className="issue__why">{issue.why}</p>

                    {issue.fix && (
                      <p className="issue__fix">
                        <strong>{issue.fix.label}.</strong> {issue.fix.description}
                      </p>
                    )}
                    {!issue.fix && (
                      <p className="issue__nofix">
                        There is no safe automatic fix for this — which side of
                        the problem is the mistake is a question about your data
                        that only you can answer.
                      </p>
                    )}

                    {/* Outlier issues name specific ROWS, and that is the
                        difference between "3 anomalies detected" -- a statistic
                        nobody can act on -- and "row 18,291 is 14x the typical
                        value", which somebody can go and look up.

                        Shown in both modes on purpose. It is the one piece of
                        detail on this screen that a non-technical reader needs
                        MORE than an expert does: the expert can find these rows
                        themselves. */}
                    {issue.evidence?.rows?.length > 0 && (
                      <table className="issue__rows">
                        <caption>The most extreme values in this column</caption>
                        <thead>
                          <tr>
                            <th scope="col">Row</th>
                            <th scope="col">Value</th>
                            <th scope="col">vs typical</th>
                          </tr>
                        </thead>
                        <tbody>
                          {issue.evidence.rows.slice(0, 6).map((row) => (
                            <tr key={row.row}>
                              <td>{row.row.toLocaleString()}</td>
                              <td>{row.display}</td>
                              <td>{row.ratio ? `${row.ratio}x` : '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}

                    <div className="issue__foot">
                      <ExplainThis
                        sessionId={sessionId}
                        target="health_issue"
                        refId={issue.id}
                        defaultLevel={mode === 'advanced' ? 'technical' : 'simple'}
                      />
                      {mode === 'advanced' && issue.penalty != null && (
                        <span className="issue__penalty">
                          costs {issue.penalty} points of the score
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>

          {/* ------------------------------------------------------ plan -- */}
          {fixable.length > 0 && (
            <div className="health__apply">
              {error && (
                <p className="health__error" role="alert">
                  {error}
                </p>
              )}

              {plan ? (
                <div className="health__plan">
                  <h3 className="health__plan-title">
                    These are the exact changes. Nothing has happened yet.
                  </h3>
                  <ol className="health__plan-list">
                    {plan.steps.map((step, index) => (
                      <li key={`${step.action}-${index}`}>
                        <span className="health__plan-action">{step.action}</span>
                        <span className="health__plan-label">{step.label}</span>
                        <span className="health__plan-desc">{step.description}</span>
                      </li>
                    ))}
                  </ol>
                  <p className="health__plan-note">{plan.note}</p>
                  <div className="health__plan-buttons">
                    <button
                      type="button"
                      className="button button--primary"
                      onClick={apply}
                      disabled={busy}
                    >
                      {busy ? 'Applying…' : `Apply these ${plan.n_steps} changes`}
                    </button>
                    <button
                      type="button"
                      className="button button--quiet"
                      onClick={() => setPlan(null)}
                      disabled={busy}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="button button--primary"
                  onClick={review}
                  disabled={busy || selected.size === 0}
                >
                  {busy
                    ? 'Working out what would change…'
                    : selected.size === 0
                      ? 'Tick something to fix'
                      : `Review the ${selected.size} change${
                          selected.size === 1 ? '' : 's'
                        } first`}
                </button>
              )}
            </div>
          )}
        </section>
      ) : (
        <p className="health__all-clear">
          Every check passed. There is nothing to fix before you analyse this.
        </p>
      )}

      {/* ---------------------------------------------------------- clean -- */}
      {clean.length > 0 && (
        <section className="health__passed">
          <h2 className="health__section-title">What was checked and was fine</h2>
          <ul className="health__passed-list">
            {clean.map((item) => (
              <li key={item.title}>
                <span className="health__passed-title">{item.title}</span>
                <span className="health__passed-detail">{item.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
