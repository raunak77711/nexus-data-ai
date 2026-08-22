import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { tokeniseLines } from '../lib/pythonHighlight'
import './CodePanel.css'

/**
 * The glass box: the exact source that produced the figure above it.
 *
 * This is the project's differentiator, so it is built as a feature rather than
 * as a debug dump. It is dark against a light page (code has its own surface,
 * the way an editor does), it is syntax highlighted, it is numbered, and it
 * tells you how long it is before you open it -- because the question a reader
 * actually has is "is this two lines or forty".
 *
 * The panel is COLLAPSED by default. That is a deliberate reading of the
 * hierarchy: the chart is the answer and the code is the evidence, so the code
 * is one click away rather than in the way. What must never happen is the code
 * being hard to FIND, which is why every figure has its own panel directly
 * beneath it rather than one shared drawer somewhere else on the page.
 *
 * ============================================================================
 * VANILLA DOM FEATURE 2 OF 2 -- clipboard writing and scroll-spy, both written
 * against the DOM API rather than through React state.
 * ============================================================================
 *
 * Two behaviours here bypass React entirely:
 *
 *  A. COPY TO CLIPBOARD reads the code out of the rendered DOM with
 *     querySelector + textContent, rather than from the prop it was rendered
 *     from. That is not incidental -- it means the button provably copies WHAT
 *     IS ON SCREEN. For a glass box whose whole claim is "the code you see is
 *     the code that ran", copying from a separate source of truth would be a
 *     small lie of exactly the kind this project exists to avoid. The fallback
 *     path builds a detached <textarea>, selects it and calls execCommand,
 *     which is the only thing that works when the page is not on a secure
 *     origin -- as http://localhost aliases sometimes are not.
 *
 *  B. SCROLL-SPY listens to the scroll event on the <pre> and writes the first
 *     visible line number into a data attribute plus a CSS custom property that
 *     drives a progress bar in the header. Scroll fires at up to the display's
 *     refresh rate; putting that through setState would re-render a
 *     several-hundred-element token tree sixty times a second for what is two
 *     attribute writes. The reads are batched into requestAnimationFrame so the
 *     handler never causes a synchronous layout mid-scroll.
 */
export default function CodePanel({ title, code, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const regionId = useId()
  const preRef = useRef(null)
  const headerRef = useRef(null)
  const copyButtonRef = useRef(null)

  // Tokenising is pure work over a string that rarely changes; memoising keeps
  // a long snippet from being re-parsed on every unrelated re-render.
  const lines = useMemo(() => tokeniseLines(code ?? ''), [code])

  /* ------------------------------------------------------------------ B --
   * Scroll-spy. Registered only while the panel is open, because a listener on
   * a collapsed element is pure cost.
   */
  useEffect(() => {
    const pre = preRef.current
    const header = headerRef.current
    if (!open || !pre || !header) return undefined

    // Read once from the DOM rather than assuming the CSS value.
    const lineHeight =
      parseFloat(window.getComputedStyle(pre).getPropertyValue('line-height')) || 20

    let frame = 0
    const update = () => {
      frame = 0
      const scrollable = pre.scrollHeight - pre.clientHeight
      const progress = scrollable > 0 ? pre.scrollTop / scrollable : 0
      const firstVisible = Math.min(lines.length, Math.floor(pre.scrollTop / lineHeight) + 1)

      // Two DOM writes, no React involved. The custom property is read by the
      // header's ::after rule to size the progress bar.
      header.dataset.line = String(firstVisible)
      header.style.setProperty('--scroll-progress', progress.toFixed(3))
      // classList for a boolean piece of decoration: a shadow under the header
      // once the code has scrolled beneath it.
      header.classList.toggle('is-scrolled', pre.scrollTop > 2)
    }

    const onScroll = () => {
      // Coalesce bursts of scroll events into one write per painted frame.
      if (!frame) frame = window.requestAnimationFrame(update)
    }

    pre.addEventListener('scroll', onScroll, { passive: true })
    update()

    return () => {
      pre.removeEventListener('scroll', onScroll)
      if (frame) window.cancelAnimationFrame(frame)
      header.classList.remove('is-scrolled')
      delete header.dataset.line
      header.style.removeProperty('--scroll-progress')
    }
  }, [open, lines.length])

  /* ------------------------------------------------------------------ A --
   * Copy to clipboard, reading from the rendered DOM.
   */
  const handleCopy = async () => {
    const button = copyButtonRef.current
    const pre = preRef.current
    if (!button || !pre) return

    // The gutter is a sibling element, so textContent on the code element alone
    // yields the source without line numbers glued to the front of each line.
    const codeEl = pre.querySelector('code')
    const text = codeEl ? codeEl.textContent : ''

    let ok = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        ok = true
      } else {
        ok = legacyCopy(text)
      }
    } catch {
      // Permissions policy, insecure origin, or a user denying the prompt.
      ok = legacyCopy(text)
    }

    // Confirmation written straight onto the element. A ~1.6s data attribute is
    // both cheaper and less error-prone than a state flag plus a cleanup effect
    // that has to survive the component unmounting mid-timeout.
    button.dataset.copied = ok ? 'yes' : 'failed'
    window.setTimeout(() => {
      if (copyButtonRef.current) delete copyButtonRef.current.dataset.copied
    }, 1600)
  }

  if (!code) return null

  return (
    <div className="code-panel" data-open={open ? 'yes' : 'no'}>
      <div ref={headerRef} className="code-panel-header">
        <button
          type="button"
          className="code-panel-toggle"
          aria-expanded={open}
          aria-controls={regionId}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="code-chevron" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m6 4 4 4-4 4" />
            </svg>
          </span>
          <span className="code-panel-label">
            {open ? 'Hide' : 'Show'} the code
          </span>
          <span className="code-panel-title">{title}</span>
        </button>

        <span className="code-panel-meta tnum" aria-hidden="true">
          {lines.length} lines
        </span>

        <button
          ref={copyButtonRef}
          type="button"
          className="code-copy"
          onClick={handleCopy}
          disabled={!open}
          title={open ? 'Copy this snippet' : 'Open the panel to copy'}
        >
          <span className="code-copy-idle">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor"
                 strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="5.5" y="5.5" width="8" height="8" rx="1.6" />
              <path d="M10.5 3.5a1.6 1.6 0 0 0-1.6-1.6H4a1.6 1.6 0 0 0-1.6 1.6v5a1.6 1.6 0 0 0 1.6 1.6" />
            </svg>
            Copy
          </span>
          <span className="code-copy-done" aria-hidden="true">Copied</span>
          <span className="code-copy-failed" aria-hidden="true">Press Ctrl+C</span>
        </button>
      </div>

      {/* The 0fr -> 1fr grid trick: it animates to the content's real height
          without anyone having to measure it in JavaScript, and it collapses to
          genuinely zero rather than to a guessed max-height. */}
      <div className="code-panel-shutter" id={regionId} role="region" aria-label={`Code for ${title}`}>
        <div className="code-panel-shutter-inner">
          <pre ref={preRef} className="code-pre" tabIndex={0}>
            <span className="code-gutter" aria-hidden="true">
              {lines.map((_, index) => (
                <span key={index} className="code-gutter-line">{index + 1}</span>
              ))}
            </span>
            <code className="code-body">
              {lines.map((tokens, index) => (
                <span key={index} className="code-line">
                  {tokens.map((token, tokenIndex) => (
                    <span key={tokenIndex} className={`tok tok-${token.type}`}>
                      {token.text}
                    </span>
                  ))}
                  {'\n'}
                </span>
              ))}
            </code>
          </pre>

          <p className="code-panel-footnote">
            This is not a description of what ran — it <em>is</em> what ran. The
            figure above was produced by executing this exact text.
          </p>
        </div>
      </div>
    </div>
  )
}

/**
 * Clipboard fallback for non-secure origins, using only the DOM API.
 *
 * document.execCommand('copy') is deprecated but not removed, and it is still
 * the only route that works without the async Clipboard API's secure-context
 * requirement. The textarea is positioned off-screen rather than hidden,
 * because a display:none element cannot be selected.
 */
function legacyCopy(text) {
  const scratch = document.createElement('textarea')
  scratch.value = text
  scratch.setAttribute('readonly', '')
  scratch.style.position = 'fixed'
  scratch.style.top = '-1000px'
  scratch.style.opacity = '0'
  document.body.appendChild(scratch)
  scratch.select()

  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(scratch)
  return ok
}
