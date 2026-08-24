import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as api from '../api'
import PlotFigure from './PlotFigure'
import Provenance from './Provenance'
import './Assistant.css'

/**
 * The AI analyst. One panel, available on every screen, aware of what is open.
 *
 * WHY IT IS THE SAME COMPONENT BEFORE AND AFTER AN UPLOAD
 * ------------------------------------------------------
 * The moment somebody is most likely to give up is the moment BEFORE they
 * upload anything — they are holding a file and are not sure this will help.
 * An assistant that only appears once you have succeeded arrives after the
 * hard part. So this mounts on the landing page too, and the server decides
 * which assistant answers: with a dataset it is the one that runs calculations,
 * without one it is the guide that explains the product. The panel does not
 * need to know which, and deliberately does not branch on it.
 *
 * THE THREE THINGS AN ANSWER CAN CARRY, AND WHY EACH IS RENDERED
 * -------------------------------------------------------------
 *   answered_by  how the answer was reached. Rendered as a provenance mark,
 *                because "the model wrote this sentence around numbers pandas
 *                computed" and "the model is talking" are different claims and
 *                a chat window is where they are hardest to tell apart.
 *   action       a chart spec that shows the answer. Fetched on demand — an
 *                answer with a chart attached is not the same as an answer that
 *                should interrupt itself to draw one.
 *   followups    what to ask next. The feature that turns a question box into
 *                something that feels like an analyst; see core/followup.py for
 *                why each suggestion is a different KIND of next question
 *                rather than three rewordings of the same one.
 */

const OPENING = {
  role: 'assistant',
  content: 'How can I help you understand your data today?',
  opening: true,
}

/** Shown before an upload, when there is no dataset to suggest questions about. */
const COLD_PROMPTS = [
  'What kind of files can I use?',
  'What will you actually tell me?',
  'Do I need to know statistics?',
]

export default function Assistant({
  open,
  onClose,
  sessionId,
  filename,
  suggestions = [],
  pendingQuestion,
  onPendingConsumed,
}) {
  const [messages, setMessages] = useState([OPENING])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  const send = useCallback(
    async (text) => {
      const question = String(text ?? '').trim()
      if (!question || busy) return

      // The history sent to the server is the conversation WITHOUT the opening
      // greeting and without the assistant's own suggestion chips. Replaying a
      // greeting as context teaches the model that this conversation begins
      // with it saying something it did not compute.
      const history = messages
        .filter((message) => !message.opening)
        .map(({ role, content }) => ({ role, content }))

      setMessages((current) => [...current, { role: 'user', content: question }])
      setDraft('')
      setBusy(true)

      try {
        const result = sessionId
          ? await api.sendChat(sessionId, question, history)
          : await api.askAssistant(question, history, null)

        setMessages((current) => [
          ...current,
          {
            role: 'assistant',
            content: result.reply,
            answeredBy: result.answered_by,
            action: result.action ?? null,
            table: result.table ?? null,
            followups: result.followups ?? [],
          },
        ])
      } catch (caught) {
        setMessages((current) => [
          ...current,
          {
            role: 'assistant',
            content: caught.message,
            failed: true,
          },
        ])
      } finally {
        setBusy(false)
      }
    },
    [busy, messages, sessionId],
  )

  /**
   * A question clicked elsewhere in the app — a suggested question on the story
   * screen, say — arrives here as `pendingQuestion`. It opens the panel and
   * asks, then tells the parent it has been consumed so the same question is
   * not re-sent on the next render.
   */
  useEffect(() => {
    if (!pendingQuestion) return
    send(pendingQuestion)
    onPendingConsumed?.()
    // `send` is intentionally omitted: it changes identity on every message,
    // and including it would re-fire the pending question after each reply.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion])

  /** Keep the newest message in view as the conversation grows. */
  useLayoutEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, busy])

  /** Focus the input when the panel opens, so typing can start immediately. */
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  /** Escape closes it, which is what every drawer in every app does. */
  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const prompts = sessionId
    ? suggestions.slice(0, 3).map((item) => item.text)
    : COLD_PROMPTS

  return (
    <>
      {/* The scrim is click-to-close on small screens where the panel covers
          the page. On wide screens the panel is a column beside the content and
          the scrim is not rendered at all, so the page stays usable behind it. */}
      {open && <div className="assistant__scrim" onClick={onClose} aria-hidden="true" />}

      <aside
        className={`assistant ${open ? 'assistant--open' : ''}`.trim()}
        aria-label="AI analyst"
        aria-hidden={!open}
        // Inert while closed, so a keyboard user does not tab into a panel that
        // is sliding off screen. React 19 maps a boolean straight onto the HTML
        // attribute; an empty string would be treated as the string "false" is
        // -- present, and therefore true -- disabling the panel while OPEN.
        inert={!open}
      >
        <header className="assistant__head">
          <div>
            <p className="assistant__title">AI analyst</p>
            {filename ? (
              <p className="assistant__context" title={filename}>
                Looking at {filename}
              </p>
            ) : (
              <p className="assistant__context">No file open yet</p>
            )}
          </div>
          <button
            type="button"
            className="assistant__close"
            onClick={onClose}
            aria-label="Close the AI analyst"
          >
            <CloseIcon />
          </button>
        </header>

        <div className="assistant__scroll" ref={scrollRef}>
          {messages.map((message, index) => (
            <Message
              key={`${message.role}-${index}`}
              message={message}
              sessionId={sessionId}
              onAsk={send}
            />
          ))}

          {busy && (
            <div className="bubble bubble--assistant">
              <span className="assistant__thinking" aria-label="Working it out">
                <i /> <i /> <i />
              </span>
            </div>
          )}
        </div>

        {/* Prompts sit above the input rather than inside the transcript, so
            they do not scroll away the moment a conversation starts. */}
        {prompts.length > 0 && messages.length <= 1 && (
          <div className="assistant__prompts">
            {prompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                className="assistant__prompt"
                onClick={() => send(prompt)}
                disabled={busy}
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        <form
          className="assistant__form"
          onSubmit={(event) => {
            event.preventDefault()
            send(draft)
          }}
        >
          <label className="sr-only" htmlFor="assistant-input">
            Ask about your data
          </label>
          <textarea
            id="assistant-input"
            ref={inputRef}
            className="assistant__input"
            value={draft}
            rows={1}
            placeholder={
              sessionId ? 'Ask anything about this data…' : 'Ask about this app…'
            }
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter breaks the line. The convention every
              // chat interface uses, and the one people try first.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send(draft)
              }
            }}
            disabled={busy}
          />
          <button
            type="submit"
            className="assistant__send"
            disabled={busy || !draft.trim()}
            aria-label="Send"
          >
            <SendIcon />
          </button>
        </form>
      </aside>
    </>
  )
}

/** One turn, plus everything the server attached to it. */
function Message({ message, sessionId, onAsk }) {
  const [chart, setChart] = useState(null)
  const [chartError, setChartError] = useState('')

  const showChart = useCallback(async () => {
    if (chart || !message.action) return
    try {
      setChart(await api.buildChart(sessionId, message.action))
    } catch (caught) {
      setChartError(caught.message)
    }
  }, [chart, message.action, sessionId])

  if (message.role === 'user') {
    return <div className="bubble bubble--user">{message.content}</div>
  }

  return (
    <div className={`bubble bubble--assistant ${message.failed ? 'bubble--failed' : ''}`.trim()}>
      <p className="bubble__text">{message.content}</p>

      {/* A table of results, when the answer is a list rather than a number. */}
      {message.table?.rows?.length > 0 && (
        <div className="bubble__table-wrap">
          <table className="bubble__table">
            <thead>
              <tr>
                {message.table.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {message.table.rows.map((row, index) => (
                // eslint-disable-next-line react/no-array-index-key -- rank order is the identity
                <tr key={index}>
                  {row.map((cell, cellIndex) => (
                    <td key={message.table.columns[cellIndex] ?? cellIndex}>
                      {formatCell(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {message.action && !chart && (
        <button type="button" className="bubble__chart-button" onClick={showChart}>
          Show me that as a chart
        </button>
      )}
      {chartError && <p className="bubble__error">{chartError}</p>}
      {chart?.figure_json && (
        <div className="bubble__chart">
          <PlotFigure figureJson={chart.figure_json} height={220} />
        </div>
      )}

      {message.answeredBy && (
        <Provenance
          kind={PROVENANCE_BY_ANSWER[message.answeredBy] ?? 'computed'}
          className="bubble__mark"
        />
      )}

      {message.followups?.length > 0 && (
        <div className="bubble__followups">
          <p className="bubble__followups-label">You might also ask</p>
          {message.followups.map((followup) => (
            <button
              key={followup.text}
              type="button"
              className="bubble__followup"
              onClick={() => onAsk(followup.text)}
            >
              {followup.text}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * A table cell, rounded for reading.
 *
 * pandas returns full float precision -- a mean arrives as 183.21083333333334 --
 * and printing that verbatim makes a computed answer look like a debug dump.
 * Rounding is presentation only and never changes which number is shown; the
 * full value is still what every calculation downstream used.
 *
 * Two decimals, except for values large enough that decimals are noise, where
 * thousands separators do more for legibility.
 */
function formatCell(cell) {
  if (cell === null || cell === undefined) return '—'
  if (typeof cell !== 'number' || !Number.isFinite(cell)) return String(cell)
  if (Number.isInteger(cell)) return cell.toLocaleString()
  if (Math.abs(cell) >= 1000) return cell.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return cell.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

/**
 * How the server's `answered_by` maps onto a provenance mark.
 *
 * "computed" means pandas produced the numbers AND the wording is templated, so
 * nothing about it came from a model. "model" means pandas produced the numbers
 * and the model wrote the sentence — which is exactly what `worded` means.
 * "summaries" answered from cached statistics without a fresh calculation, and
 * is still a computed figure. Only an outright failure has no mark.
 */
const PROVENANCE_BY_ANSWER = {
  computed: 'computed',
  model: 'worded',
  summaries: 'computed',
  unavailable: 'computed',
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 14 14" aria-hidden="true" className="assistant__icon">
      <path
        d="M3.5 3.5l7 7M10.5 3.5l-7 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="assistant__icon">
      <path
        d="M2 8h10M8 4l4 4-4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
