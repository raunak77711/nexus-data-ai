import { useCallback, useState } from 'react'
import * as api from '../api'
import Provenance from './Provenance'
import './ExplainThis.css'

/**
 * "Explain this" — attached to every chart, finding and data issue.
 *
 * WHY IT FETCHES LAZILY AND THEN REMEMBERS. Explaining costs a model round
 * trip. Prefetching one for every panel on a six-chart dashboard would mean
 * six requests nobody asked for, on a page most people will read without
 * pressing anything. So nothing happens until the button is pressed — and once
 * pressed, the answer is kept, including when the panel is collapsed and
 * reopened, because paying twice for the same sentence is the same waste in a
 * smaller package.
 *
 * WHY BOTH LEVELS ARE CACHED SEPARATELY. They are different answers, not one
 * answer with more detail, so switching to Technical fetches once and then
 * toggling between the two is free. That matters more than it sounds: the
 * toggle is only worth having if it feels instant, and a toggle that costs two
 * seconds each way is one nobody flips twice.
 */

const LEVELS = [
  { id: 'simple', label: 'Simple', hint: 'Plain language, no statistics' },
  { id: 'technical', label: 'Technical', hint: 'Method, assumptions and limits' },
]

export default function ExplainThis({ sessionId, target, refId, defaultLevel = 'simple' }) {
  const [open, setOpen] = useState(false)
  const [level, setLevel] = useState(defaultLevel)
  // Keyed by level, so the two registers do not overwrite each other.
  const [answers, setAnswers] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchLevel = useCallback(
    async (wanted) => {
      if (answers[wanted]) return
      setLoading(true)
      setError('')
      try {
        const result = await api.explain(sessionId, { target, ref: refId, level: wanted })
        setAnswers((current) => ({ ...current, [wanted]: result }))
      } catch (caught) {
        setError(caught.message)
      } finally {
        setLoading(false)
      }
    },
    [answers, sessionId, target, refId],
  )

  const toggleOpen = useCallback(() => {
    const next = !open
    setOpen(next)
    if (next) fetchLevel(level)
  }, [open, level, fetchLevel])

  const chooseLevel = useCallback(
    (wanted) => {
      setLevel(wanted)
      fetchLevel(wanted)
    },
    [fetchLevel],
  )

  const answer = answers[level]

  return (
    <div className="explain">
      <button
        type="button"
        className="explain__trigger"
        onClick={toggleOpen}
        aria-expanded={open}
      >
        <SparkIcon />
        {open ? 'Hide explanation' : 'Explain this'}
      </button>

      {open && (
        <div className="explain__body">
          <div className="explain__levels" role="group" aria-label="Explanation detail">
            {LEVELS.map((option) => (
              <button
                key={option.id}
                type="button"
                className="explain__level"
                aria-pressed={level === option.id}
                onClick={() => chooseLevel(option.id)}
                title={option.hint}
              >
                {option.label}
              </button>
            ))}
          </div>

          {/* Only shown while there is nothing to read. Once an answer for the
              other level has arrived, switching back must not blank the text
              that is already on screen — a panel that empties itself when you
              press a toggle reads as a failure. */}
          {loading && !answer && (
            <p className="explain__loading">
              <span className="explain__pulse" aria-hidden="true" />
              Working out how to put this…
            </p>
          )}

          {error && !answer && <p className="explain__error">{error}</p>}

          {answer && (
            <>
              <p className="explain__text">{answer.text}</p>
              <Provenance
                kind={answer.source === 'llm' ? 'worded' : 'computed'}
                className="explain__mark"
              />
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The one piece of iconography in the app that means "AI did this".
 *
 * A four-pointed spark rather than a robot, a brain or a chat bubble. Those
 * three are the genre's stock icons and all of them personify the model, which
 * is the opposite of what this interface is claiming — the model here is a
 * writer, not a mind, and it never touches a number.
 */
function SparkIcon() {
  return (
    <svg
      className="explain__spark"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M8 1.5 9.3 6.7 14.5 8 9.3 9.3 8 14.5 6.7 9.3 1.5 8 6.7 6.7z"
        fill="currentColor"
      />
    </svg>
  )
}
