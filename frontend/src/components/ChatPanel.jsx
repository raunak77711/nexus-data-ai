import { useEffect, useRef, useState } from 'react'
import './ChatPanel.css'

/**
 * Ask questions about the uploaded dataset.
 *
 * THE ONE THING THIS UI MUST DO, beyond looking like a chat: show the grounding.
 * Every assistant reply carries the list of context blocks the answer was
 * allowed to draw on, rendered underneath it. That line is not decoration and
 * it is not a debug affordance -- it is the difference between "the app said
 * 42" and "the app said 42, from the timeseries statistics". The user can then
 * go and look at those statistics, which are on the same page.
 *
 * A reply with an EMPTY grounding list is styled differently and labelled
 * "answered without using the summaries", because that is what the assistant
 * returns when it declined to answer. That case is not hidden or softened: an
 * honest "I only have the summary, not the rows" is the correct outcome for a
 * question the context cannot support, and the interface should present it as a
 * success rather than as a shrug.
 */

/** Names the backend uses for context blocks -> what to call them on screen. */
const BLOCK_LABELS = {
  profile: 'column profile',
  routing: 'routing decision',
  timeseries_stats: 'timeseries statistics',
  geo_stats: 'map statistics',
  tabular_stats: 'table statistics',
  world_stats: 'chart statistics',
  forecast_metrics: 'forecast metrics',
}

const SUGGESTIONS = [
  'What is this dataset about?',
  'Which column has the most missing values?',
  'Why was this archetype chosen?',
  'Did the forecast beat the baseline?',
]

export default function ChatPanel({ onSend, disabled }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const logRef = useRef(null)
  const inputRef = useRef(null)

  // Keep the newest message in view. `behavior: smooth` is left to the global
  // reduced-motion override in base.css rather than being branched on here.
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
    setError('')
    setPending(true)

    try {
      const reply = await onSend(text, priorHistory)
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: reply.reply,
          groundedOn: reply.grounded_on ?? [],
          available: reply.available !== false,
        },
      ])
    } catch (requestError) {
      // The question stays in the log, marked, rather than disappearing: the
      // user should not have to retype it, and a chat that silently swallows a
      // turn is worse than one that admits the turn failed.
      setError(requestError.message)
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: `I could not reach the assistant. ${requestError.message}`,
          groundedOn: [],
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
    <section className="chat panel" aria-labelledby="chat-heading">
      <header className="chat-head">
        <h2 id="chat-heading">Ask about this dataset</h2>
        <p className="chat-sub">
          Answers come from the profile, the routing and the computed statistics —
          never from the rows, and never from a calculation the assistant made up.
        </p>
      </header>

      <div
        ref={logRef}
        className="chat-log"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {messages.length === 0 && !pending && (
          <div className="chat-empty">
            <p>Try one of these:</p>
            <ul className="chat-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  <button
                    type="button"
                    className="chat-suggestion"
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
          <article
            key={index}
            className="chat-turn"
            data-role={entry.role}
            data-available={entry.available === false ? 'no' : 'yes'}
          >
            <p className="chat-role">{entry.role === 'user' ? 'You' : 'Assistant'}</p>
            <div className="chat-bubble">
              {/* Rendered as plain text, split on blank lines. Deliberately not
                  markdown: the reply is model output, and running model output
                  through an HTML renderer is how a prompt injection in a column
                  name becomes markup on the page. */}
              {String(entry.content)
                .split(/\n{2,}/)
                .map((paragraph, pIndex) => (
                  <p key={pIndex}>{paragraph}</p>
                ))}
            </div>

            {entry.role === 'assistant' && entry.available !== false && (
              <p className="chat-grounding" data-empty={entry.groundedOn.length ? 'no' : 'yes'}>
                {entry.groundedOn.length > 0 ? (
                  <>
                    <span className="chat-grounding-label">Grounded on</span>
                    {entry.groundedOn.map((block) => (
                      <span key={block} className="badge chat-block">
                        {BLOCK_LABELS[block] ?? block}
                      </span>
                    ))}
                  </>
                ) : (
                  <span className="chat-grounding-label">
                    No summary answered this — the assistant said so rather than guessing.
                  </span>
                )}
              </p>
            )}
          </article>
        ))}

        {pending && (
          <article className="chat-turn" data-role="assistant">
            <p className="chat-role">Assistant</p>
            <div className="chat-bubble chat-thinking" aria-label="Thinking">
              <span /><span /><span />
            </div>
          </article>
        )}
      </div>

      {error && (
        <p className="status-note" data-tone="error">
          {error}
        </p>
      )}

      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault()
          ask(draft)
        }}
      >
        <label className="visually-hidden" htmlFor="chat-input">
          Your question about this dataset
        </label>
        <input
          ref={inputRef}
          id="chat-input"
          className="chat-input"
          type="text"
          autoComplete="off"
          maxLength={4000}
          placeholder="Which column has the most missing values?"
          value={draft}
          disabled={disabled || pending}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="submit"
          className="btn btn-primary chat-send"
          disabled={disabled || pending || !draft.trim()}
        >
          Ask
        </button>
      </form>
    </section>
  )
}
