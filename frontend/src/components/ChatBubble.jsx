import { useEffect, useRef, useState } from 'react'
import './ChatBubble.css'

/**
 * The help bubble, in the corner of every screen including the home page.
 *
 * WHY IT IS HERE BEFORE THERE IS ANY DATA. The moment a first-time visitor is
 * most likely to give up is the moment before they upload anything — they are
 * looking at a box and wondering whether their file will work, whether they
 * need an account, and whether this is going to be complicated. An assistant
 * that only appears after a successful upload is an assistant that arrives
 * after the hard part.
 *
 * So it opens with a question rather than a feature list, and the server puts
 * whichever assistant fits behind it: help about the app before a file is
 * loaded, and real calculations over the rows once one is.
 *
 * WHAT IS DELIBERATELY ABSENT. There is no "clear conversation", no settings,
 * no model name, no token count, no source badge, no export. Every one of those
 * is a control the person this screen was designed for does not want and has to
 * read past. The one label that survived is a quiet note under an answer that
 * used their data, because "this number came from your file" is reassurance
 * rather than machinery.
 */

/** What to offer before anything is uploaded: all about getting started. */
const HOME_PROMPTS = [
  'What can I do here?',
  'What kind of file do I need?',
  'Is my data private?',
]

/** And after: questions about their own file, phrased the way a person asks. */
const DATA_PROMPTS = [
  'What does my data show?',
  'What should I look at first?',
  'Is anything going up or down?',
]

export default function ChatBubble({ onSend, hasData, disabled, openRef }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)

  const logRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  /**
   * Hand the parent a way to open this, without lifting `open` out of here.
   *
   * The Ready screen's primary action is "Ask a question", and it has to reach
   * across the tree to a component that is not its child. The alternatives were
   * to hoist `open` into App — putting a piece of purely local UI state two
   * levels above the only thing that reads it — or to add a context provider
   * for one boolean. A ref holding one function is the smaller of the three,
   * and it keeps every other piece of this component's state where it belongs.
   */
  useEffect(() => {
    if (!openRef) return undefined
    openRef.current = () => setOpen(true)
    return () => {
      openRef.current = null
    }
  }, [openRef])

  // Escape closes it from anywhere. A panel that can only be dismissed by
  // finding its close button is a panel people leave open.
  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [messages, pending])

  const ask = async (question) => {
    const text = question.trim()
    if (!text || pending || disabled) return

    // The history sent up is the conversation BEFORE this question, which is
    // what the API's `history` field means. Appending first and slicing after
    // would be one off-by-one away from sending the question twice.
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
          // `about === 'data'` means a calculation ran over the real rows.
          usedData: reply.about === 'data' && reply.available !== false,
        },
      ])
    } catch (error) {
      // The question stays in the log, marked, rather than vanishing: nobody
      // should have to retype what they just asked, and a chat that silently
      // swallows a turn is worse than one that admits the turn failed.
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: `Sorry, I could not answer just then. ${error.message}`,
          failed: true,
        },
      ])
    } finally {
      setPending(false)
      inputRef.current?.focus()
    }
  }

  const prompts = hasData ? DATA_PROMPTS : HOME_PROMPTS

  return (
    <>
      <div className="chat-panel" data-open={open ? 'yes' : 'no'} inert={!open}>
        <header className="chat-head">
          <span className="chat-avatar" aria-hidden="true">
            <Sparkle />
          </span>
          <div className="chat-head-text">
            <p className="chat-head-name">NEXUS Helper</p>
            <p className="chat-head-state">
              {disabled ? 'Not connected' : 'Here to help'}
            </p>
          </div>
          <button
            type="button"
            className="chat-close"
            onClick={() => setOpen(false)}
            aria-label="Close the chat"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                 strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <div
          ref={logRef}
          className="chat-log"
          role="log"
          aria-live="polite"
          aria-label="Chat messages"
        >
          {messages.length === 0 && (
            <div className="chat-welcome">
              <p className="chat-greeting">How can I help you today?</p>
              <p className="chat-greeting-sub">
                Ask me anything — about your file, or about how this works.
              </p>
            </div>
          )}

          {messages.map((entry, index) => (
            <div key={index} className="chat-row" data-role={entry.role}>
              <div className="chat-bubble-msg" data-failed={entry.failed ? 'yes' : 'no'}>
                {/* Rendered as plain text split on blank lines. Deliberately
                    NOT markdown: this is model output, and putting model output
                    through an HTML renderer is how text inside somebody's
                    spreadsheet becomes markup on the page. */}
                {String(entry.content)
                  .split(/\n{2,}/)
                  .map((paragraph, pIndex) => (
                    <p key={pIndex}>{paragraph}</p>
                  ))}

                {entry.usedData && (
                  <p className="chat-note">Worked out from your file</p>
                )}
              </div>
            </div>
          ))}

          {pending && (
            <div className="chat-row" data-role="assistant">
              <div className="chat-bubble-msg chat-typing" aria-label="Typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
        </div>

        {/* Suggestions stay visible for the whole conversation rather than only
            on the empty state. Somebody who has asked one question and got an
            answer is precisely the person who now wants to know what else they
            are allowed to ask. */}
        <div className="chat-prompts">
          {prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className="chat-prompt"
              onClick={() => ask(prompt)}
              disabled={disabled || pending}
            >
              {prompt}
            </button>
          ))}
        </div>

        <form
          className="chat-form"
          onSubmit={(event) => {
            event.preventDefault()
            ask(draft)
          }}
        >
          <label className="visually-hidden" htmlFor="chat-input">
            Type your question
          </label>
          <input
            ref={inputRef}
            id="chat-input"
            className="chat-input"
            type="text"
            autoComplete="off"
            maxLength={4000}
            placeholder="Type your question…"
            value={draft}
            disabled={disabled || pending}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button
            type="submit"
            className="chat-send"
            disabled={disabled || pending || !draft.trim()}
            aria-label="Send"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12h13M12 5l7 7-7 7" />
            </svg>
          </button>
        </form>
      </div>

      {/* The launcher carries the greeting as a label the first time, so the
          offer is legible without anybody having to click to discover it. */}
      <button
        type="button"
        className="chat-launcher"
        data-open={open ? 'yes' : 'no'}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label={open ? 'Close the chat' : 'Open the chat — how can I help you today?'}
      >
        <span className="chat-launcher-icon" aria-hidden="true">
          <Sparkle />
        </span>
        <span className="chat-launcher-text">Need help?</span>
      </button>
    </>
  )
}

/** The helper's face: the same three-node glyph as the brand mark, simplified. */
function Sparkle() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <circle cx="12" cy="12" r="3.4" />
    </svg>
  )
}
