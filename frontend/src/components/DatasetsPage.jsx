import { useCallback, useEffect, useState } from 'react'
import * as api from '../api'
import ScoreDial from './ScoreDial'
import './DatasetsPage.css'

/**
 * My Datasets -- everything on the server, as a page of its own.
 *
 * WHY THIS IS SEPARATE FROM components/DatasetsView
 * -------------------------------------------------
 * They look similar and answer different questions. This one is a LIBRARY: it
 * exists without a dataset open, its job is to get you into one, and it is
 * reachable from the navbar on any screen. DatasetsView lives inside the
 * analyse workspace and its job is COMPARISON -- it needs an open dataset to
 * compare against, and every row there is a candidate baseline rather than a
 * destination.
 *
 * Merging them would mean one component that behaves differently depending on
 * whether a session exists, with half its controls disabled on half its
 * renders. Two small components with one clear job each is the cheaper answer.
 *
 * THE EMPTY STATE IS THE MOST IMPORTANT STATE HERE. A first-time visitor who
 * clicks Datasets in the navbar sees it, and "no data" is a dead end unless it
 * carries the way out -- so it carries the upload action itself.
 */
export default function DatasetsPage({ onOpen, onUpload, currentId, disabled }) {
  const [datasets, setDatasets] = useState(null)
  const [error, setError] = useState('')
  const [removing, setRemoving] = useState(null)

  const load = useCallback(async () => {
    setError('')
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

  const remove = useCallback(
    async (id) => {
      setRemoving(id)
      try {
        await api.deleteDataset(id)
        await load()
      } catch (caught) {
        setError(caught.message)
      } finally {
        setRemoving(null)
      }
    },
    [load],
  )

  return (
    <div className="library">
      <header className="library__head">
        <p className="eyebrow">Your library</p>
        <h1 className="library__title">My Datasets</h1>
        <p className="library__lede">
          Everything you have added, kept on the server so you can come back to
          an analysis rather than run it again.
        </p>
      </header>

      {error && (
        <p className="status-note library__status" data-tone="error" role="alert">
          <span>
            <strong>Something went wrong.</strong> {error}{' '}
            <button type="button" className="library__retry" onClick={load}>
              Try again
            </button>
          </span>
        </p>
      )}

      {datasets === null && <LibrarySkeleton />}

      {datasets?.length === 0 && !error && (
        <div className="library__empty">
          <h2 className="library__empty-title">Your data journey starts here.</h2>
          <p className="library__empty-lede">
            Upload your first dataset and let Nexus understand it.
          </p>
          <button
            type="button"
            className="btn btn-primary library__empty-action"
            onClick={onUpload}
            disabled={disabled}
          >
            Upload dataset
          </button>
        </div>
      )}

      {datasets && datasets.length > 0 && (
        <ul className="library__grid">
          {datasets.map((dataset, index) => (
            <DatasetCard
              key={dataset.id}
              dataset={dataset}
              index={index}
              isCurrent={dataset.id === currentId}
              busy={removing === dataset.id}
              onOpen={onOpen}
              onRemove={remove}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

/** One dataset. Everything a person recognises theirs by, and one way in. */
function DatasetCard({ dataset, index, isCurrent, busy, onOpen, onRemove }) {
  return (
    <li
      className="dcard"
      style={{ '--i': index }}
      data-current={isCurrent ? 'true' : undefined}
    >
      <div className="dcard__top">
        <div className="dcard__id">
          <h2 className="dcard__name" title={dataset.filename}>
            {dataset.filename}
          </h2>
          <p className="dcard__badges">
            {isCurrent && <span className="dcard__badge">open</span>}
            {dataset.is_cleaned && (
              <span className="dcard__badge dcard__badge--quiet">cleaned</span>
            )}
            {!dataset.analysed && (
              <span className="dcard__badge dcard__badge--quiet">not analysed</span>
            )}
          </p>
        </div>

        {/* The dial is the one graphic on the card, and it is a real number.
            A dataset that has not been analysed yet gets a dash rather than a
            zero -- a score of nothing and a score of zero are different, and
            drawing an empty ring for the first is how a card lies. */}
        <div className="dcard__score">
          {dataset.health_score != null ? (
            <ScoreDial score={dataset.health_score} size={46} />
          ) : (
            <span className="dcard__score-none" title="Not analysed yet">
              &mdash;
            </span>
          )}
        </div>
      </div>

      <dl className="dcard__stats">
        <div>
          <dt>Rows</dt>
          <dd className="tnum">{dataset.n_rows.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Columns</dt>
          <dd className="tnum">{dataset.n_cols}</dd>
        </div>
        <div>
          <dt>Health</dt>
          <dd>{dataset.health_grade ?? '—'}</dd>
        </div>
        <div>
          <dt>Last analysed</dt>
          <dd>{formatWhen(dataset.last_seen ?? dataset.created_at)}</dd>
        </div>
      </dl>

      <div className="dcard__actions">
        <button
          type="button"
          className="dcard__open"
          onClick={() => onOpen(dataset)}
        >
          {isCurrent ? 'Back to analysis' : 'Open dataset'}
          <span className="dcard__arrow" aria-hidden="true">
            &rarr;
          </span>
        </button>

        <button
          type="button"
          className="dcard__remove"
          onClick={() => onRemove(dataset.id)}
          disabled={busy || isCurrent}
          title={
            isCurrent
              ? 'This is the dataset you have open. Open another one first.'
              : 'Delete this dataset and its stored copy'
          }
        >
          {busy ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </li>
  )
}

/**
 * The loading state.
 *
 * Three cards of the right shape rather than a spinner, so the page does not
 * jump when the real ones land and the wait reads as "these are arriving"
 * rather than as "something is happening somewhere".
 */
function LibrarySkeleton() {
  return (
    <ul className="library__grid" aria-hidden="true">
      {[0, 1, 2].map((n) => (
        <li key={n} className="dcard dcard--ghost">
          <div className="skeleton dcard__ghost-line dcard__ghost-line--title" />
          <div className="skeleton dcard__ghost-line" />
          <div className="skeleton dcard__ghost-line dcard__ghost-line--short" />
        </li>
      ))}
    </ul>
  )
}

/**
 * When a dataset was last opened, in the shortest form that is still exact.
 *
 * Relative for the first day ("2 hours ago") because that is how people think
 * about something they were just working on; absolute after that, because
 * "14 days ago" is arithmetic the reader has to do to get back to a date.
 */
function formatWhen(iso) {
  if (!iso) return '—'
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return '—'

  const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000)
  if (seconds < 60) return 'Just now'
  if (seconds < 3600) {
    const mins = Math.round(seconds / 60)
    return `${mins} min${mins === 1 ? '' : 's'} ago`
  }
  if (seconds < 86400) {
    const hours = Math.round(seconds / 3600)
    return `${hours} hour${hours === 1 ? '' : 's'} ago`
  }
  return then.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
