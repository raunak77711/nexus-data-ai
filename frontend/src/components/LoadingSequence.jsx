import NexusMark from './NexusMark'
import './LoadingSequence.css'

/**
 * The screen between dropping a file and seeing the dashboard.
 *
 * EVERY STAGE HERE IS REAL. `stage` is advanced by App as each request
 * actually completes — the upload returns, the routing is read, the first world
 * builds — so this cannot run ahead of the work or linger after it. A staged
 * animation on a timer is a lie about how long something took, and the moment a
 * user notices it is the moment they stop believing the rest of the numbers.
 *
 * The mark assembles as it goes: one more segment of the glyph per completed
 * stage. That is why the logo is drawn as three separate strokes — see
 * NexusMark.
 */

/**
 * The three stages, in the words a person would use for them.
 *
 * These were "Reading your data / Understanding your dataset / Building your
 * data world", with details about parsing and archetypes underneath. The work
 * is identical; the description of it is now something somebody can read
 * without wondering what a data world is, or worrying that they were supposed
 * to have built one.
 */
const STAGES = [
  {
    key: 'reading',
    label: 'Opening your file',
    detail: 'This usually takes a few seconds.',
  },
  {
    key: 'checking',
    label: 'Checking your columns',
    detail: 'Seeing what kind of information each one holds.',
  },
  {
    key: 'building',
    label: 'Getting your results ready',
    detail: 'Almost there.',
  },
]

export default function LoadingSequence({ stage = 0, filename }) {
  const current = STAGES[Math.min(stage, STAGES.length - 1)]

  return (
    <div className="sequence">
      <div className="sequence-inner">
        <div className="sequence-mark">
          <NexusMark size={56} stage={stage} strokeWidth={2.2} />
        </div>

        {/* One live region for the whole sequence, so a screen reader hears
            three short updates rather than a re-read of the entire screen. */}
        <p className="sequence-current" role="status" aria-live="polite">
          {current.label}
        </p>
        <p className="sequence-detail">{current.detail}</p>

        {filename && <p className="sequence-file tnum">{filename}</p>}

        {/* Said once, plainly, because the honest answer to "is something
            wrong?" during a wait is usually "no, and there is nothing for you
            to do" — and nobody thinks to say it. */}
        <p className="sequence-reassure">Nothing for you to do — hold tight.</p>

        <ol className="sequence-steps">
          {STAGES.map((item, index) => (
            <li
              key={item.key}
              className="sequence-step"
              data-state={
                index < stage ? 'done' : index === stage ? 'active' : 'waiting'
              }
            >
              <span className="sequence-tick" aria-hidden="true" />
              <span className="sequence-label">{item.label}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
