import { useCallback, useEffect, useState } from 'react'
import * as api from '../api'
import Provenance from './Provenance'
import ScoreDial from './ScoreDial'
import './DatasetsView.css'

/**
 * My datasets — the list, and comparing two of them.
 *
 * WHY COMPARISON LIVES HERE RATHER THAN ON ITS OWN TAB
 * ---------------------------------------------------
 * Comparing needs two datasets, and the moment you have to pick a second one
 * you are looking at a list of datasets. Splitting them would mean a Compare
 * tab whose first action is "go to the Datasets tab and come back". So the list
 * IS the picker: each row that is not the open dataset carries a Compare
 * action, and the result appears underneath.
 *
 * THE DIRECTION OF A COMPARISON IS FIXED AND STATED. The dataset you are
 * currently in is always the RESULT and the one you pick is always the
 * BASELINE — "what changed to get to what I am looking at now". Leaving that
 * ambiguous means every direction in the report could be read backwards, and a
 * report that says revenue fell when it rose is worse than no report.
 */
export default function DatasetsView({ sessionId, filename, onOpen }) {
  const [datasets, setDatasets] = useState(null)
  const [comparison, setComparison] = useState(null)
  const [comparingId, setComparingId] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setDatasets(await api.listDatasets())
    } catch (caught) {
      setError(caught.message)
      setDatasets([])
    }
  }, [])

  useEffect(() => {
    // A fetch effect: this IS the synchronisation with an external system,
    // and the request has to leave in the same tick the effect runs.
    // oxlint-disable-next-line react/set-state-in-effect
    load()
  }, [load])

  const compare = useCallback(
    async (otherId) => {
      setComparingId(otherId)
      setError('')
      setComparison(null)
      try {
        setComparison(await api.compareDatasets(sessionId, otherId))
      } catch (caught) {
        setError(caught.message)
      } finally {
        setComparingId(null)
      }
    },
    [sessionId],
  )

  const remove = useCallback(
    async (id) => {
      try {
        await api.deleteDataset(id)
        if (comparison) setComparison(null)
        await load()
      } catch (caught) {
        setError(caught.message)
      }
    },
    [comparison, load],
  )

  return (
    <div className="datasets">
      <header className="datasets__head">
        <h1 className="datasets__title">Compare against another dataset</h1>
        <p className="datasets__lede">
          Pick a file to measure <strong>{filename}</strong> against. Nexus
          reports what changed to arrive at the one you have open &mdash;
          including whether the data itself got better or worse, which is the
          difference between a number that rose and a number that only looks
          like it did.
        </p>
      </header>

      {error && (
        <p className="datasets__error" role="alert">
          {error}
        </p>
      )}

      {!datasets && <p className="datasets__loading">Loading…</p>}

      {datasets?.length === 0 && (
        <p className="datasets__empty">
          Nothing here yet. Once you have added a second file, this is where
          you compare them.
        </p>
      )}

      {datasets?.length === 1 && datasets[0].id === sessionId && (
        <p className="datasets__empty">
          This is the only dataset on the server, so there is nothing to compare
          it against yet. Add another file and it appears here.
        </p>
      )}

      {datasets && datasets.length > 0 && (
        <ul className="datasets__list">
          {datasets.map((dataset) => {
            const isCurrent = dataset.id === sessionId
            return (
              <li
                key={dataset.id}
                className="dataset"
                data-current={isCurrent ? 'true' : undefined}
              >
                <div className="dataset__score">
                  {dataset.health_score != null ? (
                    <ScoreDial score={dataset.health_score} size={44} />
                  ) : (
                    <span className="dataset__score-none" title="Not analysed yet">
                      —
                    </span>
                  )}
                </div>

                <div className="dataset__body">
                  <h2 className="dataset__name">
                    {dataset.filename}
                    {isCurrent && <span className="dataset__badge">open</span>}
                    {dataset.is_cleaned && (
                      <span className="dataset__badge dataset__badge--quiet">
                        cleaned
                      </span>
                    )}
                  </h2>
                  <p className="dataset__meta">
                    {dataset.n_rows.toLocaleString()} rows ·{' '}
                    {dataset.n_cols} columns
                    {dataset.health_grade && ` · ${dataset.health_grade}`}
                    {' · added '}
                    {formatDate(dataset.created_at)}
                  </p>
                </div>

                <div className="dataset__actions">
                  {!isCurrent && (
                    <>
                      <button
                        type="button"
                        className="dataset__action"
                        onClick={() => onOpen(dataset)}
                      >
                        Open
                      </button>
                      <button
                        type="button"
                        className="dataset__action"
                        onClick={() => compare(dataset.id)}
                        disabled={comparingId === dataset.id}
                      >
                        {comparingId === dataset.id ? 'Comparing…' : 'Compare'}
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    className="dataset__action dataset__action--danger"
                    onClick={() => remove(dataset.id)}
                    disabled={isCurrent}
                    title={
                      isCurrent
                        ? 'This is the file you have open. Open another one first.'
                        : 'Delete this dataset and its stored copy'
                    }
                  >
                    Delete
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {comparison && (
        <section className="comparison">
          <h2 className="comparison__title">
            {comparison.shape.name_a} → {comparison.shape.name_b}
          </h2>
          <p className="comparison__direction">
            Comparing what changed to arrive at {filename}, the file you have
            open.
          </p>

          <p className="comparison__summary">{comparison.summary}</p>
          <Provenance
            kind={comparison.source === 'llm' ? 'worded' : 'computed'}
            className="comparison__mark"
          />

          {comparison.comparable ? (
            <>
              <ul className="comparison__changes">
                {comparison.changes.map((change) => (
                  <li key={change.id} data-direction={change.direction}>
                    <span className="comparison__arrow" aria-hidden="true">
                      {ARROW[change.direction] ?? '·'}
                    </span>
                    <span className="comparison__change-body">
                      <strong>{change.headline}</strong>
                      <span>{change.detail}</span>
                    </span>
                    {change.pct_change != null && (
                      <span className="comparison__pct">
                        {change.pct_change > 0 ? '+' : ''}
                        {change.pct_change}%
                      </span>
                    )}
                  </li>
                ))}
              </ul>

              <p className="comparison__columns">
                {comparison.columns.shared.length} shared column
                {comparison.columns.shared.length === 1 ? '' : 's'}
                {comparison.columns.only_in_first.length > 0 &&
                  ` · ${comparison.columns.only_in_first.length} only in the first file`}
                {comparison.columns.only_in_second.length > 0 &&
                  ` · ${comparison.columns.only_in_second.length} only in the second`}
              </p>
            </>
          ) : null}
        </section>
      )}
    </div>
  )
}

/**
 * Direction glyphs.
 *
 * Text arrows rather than icons, so they inherit the type colour and sit on the
 * baseline with the sentence beside them. An icon here would need its own
 * alignment rules for four states that are already one character each.
 */
const ARROW = {
  up: '↑',
  down: '↓',
  added: '+',
  removed: '−',
  flat: '=',
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
    })
  } catch {
    return '—'
  }
}
