import { useEffect, useState } from 'react'
import * as api from '../api'
import './Timeline.css'

/**
 * What the server actually did to this dataset, with real timestamps.
 *
 * WHY THE TIMESTAMPS MATTER MORE THAN THE LIST
 * --------------------------------------------
 * Every event here was recorded at the moment the work happened, in core and in
 * the routers — not assembled at render time from the final state. That is the
 * difference between a log and a stage set, and it is visible: the gaps between
 * entries are uneven, they differ per dataset, and a slow model call shows up
 * as a slow model call. A reconstructed timeline would show the same steps at
 * the same intervals every time, which is the tell.
 *
 * It is only shown in Advanced mode. A beginner does not need a work log to
 * trust the app; somebody checking whether the app really did what it says is
 * exactly who Advanced is for.
 *
 * `version` is a cache-buster rather than data: passing the health object means
 * this refetches after a clean, when new events have been recorded.
 */
export default function Timeline({ sessionId, version }) {
  const [events, setEvents] = useState([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .getTimeline(sessionId)
      .then((result) => {
        if (!cancelled) setEvents(result.events ?? [])
      })
      .catch(() => {
        // A missing work log costs nothing the user came for. No banner.
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, version])

  if (events.length === 0) return null

  return (
    <section className="timeline">
      <button
        type="button"
        className="timeline__toggle"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        Work log · {events.length} step{events.length === 1 ? '' : 's'}
      </button>

      {open && (
        <ol className="timeline__list">
          {events.map((event, index) => (
            <li key={`${event.stage}-${event.at}-${index}`} className="timeline__event">
              <time className="timeline__time" dateTime={event.at}>
                {formatTime(event.at)}
              </time>
              <span className="timeline__stage">{event.stage.replace(/_/g, ' ')}</span>
              <span className="timeline__message">{event.message}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return '—'
  }
}
