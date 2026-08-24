import { useEffect, useRef, useState } from 'react'
import SpecChart from './SpecChart'
import './AskNexus.css'

/**
 * NEXUS AI — a side panel, not a takeover.
 *
 * The assistant is one way into the data, not the product. So it lives in a
 * drawer that opens over the page and closes again, and the dashboard behind it
 * keeps working: the answer usually points AT something on that page.
 *
 * WHAT MAKES IT NOT A CHATGPT WRAPPER, and what this component has to show:
 *
 *   * Answers are CALCULATED. The backend picks a calculation, runs it over the
 *     real rows with pandas, and only then has the model write the sentence. So
 *     every reply carries a `answered_by` label and, where one applies, the name
 *     of the calculation — rendered under the reply, not hidden.
 *   * Answers can DRAW. A reply may carry a chart spec; when it does, the chart
 *     is rendered inline with the code that produced it, exactly like every
 *     other chart in the app.
 *   * Answers can be TABLES, when the question was really "list them".
 *
 * The suggested questions are phrased the way a person would ask, not the way
 * the tools are named. That is the entire onboarding for this feature.
 */

const SUGGESTIONS = [
  'Summarise this dataset',
  'What is trending?',
  'Find unusual records',
  'Which group is doing best?',
]

/** How an answer was reached, said plainly under the reply. */
const SOURCE_LABELS = {
  computed: 'Calculated from your data',
  model: 'Calculated from your data, explained by NEXUS AI',
  summaries: 'Answered from this dataset’s statistics',
  unavailable: 'No answer produced',
}

export default function AskNexus({ open, onClose, onSend, sessionId, disabled }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const logRef = useRef(null)
  const inputRef = useRef(null)
  const panelRef = useRef(null)

  // Focus the input when the panel opens, so a keyboard user can type
  // immediately rather than tabbing in from the page behind.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  // Escape closes it, from anywhere. A drawer that can only be dismissed by
  // finding its close button is a drawer people leave open.
  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [messages, pending])

  const ask = async (question) => {
    const text = question.trim()
    if (!text || pending || disabled) return

    // The history sent to the server is the conversation BEFORE this question,
    // which is what the API's `history` field means. Appending first and then
    // slicing would be one off-by-one away from sending the question twice.
    const priorHistory = messages
      .filter((entry) => !entry.failed)
      .map(({ role, content }) => ({ role, content }))

    setMessages((current) => [...current, { role: 'user', content: text }])
    setDraft('')
    setPending(true)

    try {
      const reply = await onSend(text, priorHistory)
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: reply.reply,
          answeredBy: reply.answered_by ?? 'summaries',
          tool: reply.tool ?? null,
          action: reply.action ?? null,
          table: reply.table ?? null,
          available: reply.available !== false,
        },
      ])
    } catch (requestError) {
      // The question stays in the log, marked, rather than disappearing: the
      // user should not have to retype it, and a chat that silently swallows a
      // turn is worse than one that admits the turn failed.
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: `I could not reach NEXUS. ${requestError.message}`,
          answeredBy: 'unavailable',
          available: false,
          failed: true,
        },
      ])
    } finally {
      setPending(false)
      inputRef.current?.focus()
    }
  }

  return (
    <>
      {/* The scrim is a real button so it is announced and can be activated by
          keyboard; it duplicates the close action rather than replacing it. */}
      <button
        type="button"
        className="ask-scrim"
        data-open={open ? 'yes' : 'no'}
        tabIndex={open ? 0 : -1}
        aria-hidden={!open}
        aria-label="Close the assistant"
        onClick={onClose}
      />

      <aside
        ref={panelRef}
        className="ask-panel"
        data-open={open ? 'yes' : 'no'}
        aria-labelledby="ask-heading"
        aria-hidden={!open}
        // inert takes the closed panel's contents out of tab order and out of
        // the accessibility tree, so a keyboard user never lands inside a drawer
        // that is off-screen. React 19 forwards it as a real boolean.
        inert={!open}
      >
        <header className="ask-head">
          <div>
            <h2 id="ask-heading" className="ask-title">
              <span className="ask-spark" aria-hidden="true">
                ✦
              </span>
              NEXUS AI
            </h2>
            <p className="ask-sub">Ask anything about your data</p>
          </div>

          <button type="button" className="ask-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                 strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <div
          ref={logRef}
          className="ask-log"
          role="log"
          aria-live="polite"
          aria-label="Conversation"
        >
          {messages.length === 0 && !pending && (
            <div className="ask-intro">
              <p className="ask-intro-text">
                NEXUS answers by running a real calculation over your rows, then
                explaining the result. It will not invent a number.
              </p>
              <ul className="ask-suggestions">
                {SUGGESTIONS.map((suggestion) => (
                  <li key={suggestion}>
                    <button
                      type="button"
                      className="ask-suggestion"
                      onClick={() => ask(suggestion)}
                      disabled={disabled}
                    >
                      {suggestion}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {messages.map((entry, index) => (
            <article key={index} className="ask-turn" data-role={entry.role}>
              {entry.role === 'user' ? (
                <p className="ask-question">{entry.content}</p>
              ) : (
                <div className="ask-answer" data-available={entry.available ? 'yes' : 'no'}>
                  {/* Rendered as plain text split on blank lines. Deliberately
                      not markdown: the reply is model output, and running model
                      output through an HTML renderer is how a prompt injection
                      in a column name becomes markup on the page. */}
                  {String(entry.content)
                    .split(/\n{2,}/)
                    .map((paragraph, pIndex) => (
                      <p key={pIndex}>{paragraph}</p>
                    ))}

                  {entry.table && <AnswerTable table={entry.table} />}

                  {entry.action && sessionId && (
                    <div className="ask-chart">
                      <SpecChart
                        sessionId={sessionId}
                        spec={entry.action}
                        height={220}
                        showCode={false}
                      />
                    </div>
                  )}

                  <p className="ask-source">
                    {SOURCE_LABELS[entry.answeredBy] ?? SOURCE_LABELS.summaries}
                    {entry.tool && (
                      <span className="badge ask-tool">{friendlyTool(entry.tool)}</span>
                    )}
                  </p>
                </div>
              )}
            </article>
          ))}

          {pending && (
            <article className="ask-turn" data-role="assistant">
              <div className="ask-answer ask-thinking" aria-label="Working it out">
                <span />
                <span />
                <span />
              </div>
            </article>
          )}
        </div>

        <form
          className="ask-form"
          onSubmit={(event) => {
            event.preventDefault()
            ask(draft)
          }}
        >
          <label className="visually-hidden" htmlFor="ask-input">
            Your question about this dataset
          </label>
          <input
            ref={inputRef}
            id="ask-input"
            className="ask-input"
            type="text"
            autoComplete="off"
            maxLength={4000}
            placeholder="Which region sells the most?"
            value={draft}
            disabled={disabled || pending}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button
            type="submit"
            className="btn btn-primary ask-send"
            disabled={disabled || pending || !draft.trim()}
          >
            Ask
          </button>
        </form>
      </aside>
    </>
  )
}

/** A small result table, when the answer was really a list. */
function AnswerTable({ table }) {
  if (!table?.columns || !table?.rows) return null

  return (
    <div className="ask-table-scroll">
      <table className="ask-table">
        <thead>
          <tr>
            {table.columns.map((name) => (
              <th key={name} scope="col">
                {String(name).replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.slice(0, 8).map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className={typeof cell === 'number' ? 'tnum' : undefined}>
                  {typeof cell === 'number'
                    ? cell.toLocaleString(undefined, { maximumFractionDigits: 2 })
                    : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Tool names are internal. What the user sees is what was worked out. */
function friendlyTool(tool) {
  return (
    {
      rank: 'ranked',
      aggregate: 'totalled',
      trend: 'measured change',
      relationship: 'compared',
      outliers: 'checked for unusual rows',
      describe: 'summarised a column',
      overview: 'summarised the file',
      count: 'counted rows',
    }[tool] ?? tool
  )
}
