import { Spark } from './NavBar'
import './AnalystLauncher.css'

/**
 * The floating button that opens the AI analyst.
 *
 * WHY A FLOATING BUTTON AND NOT ONLY THE NAVBAR ENTRY
 * ---------------------------------------------------
 * The analyst is the product, not a support widget, and the navbar is above
 * the fold only. Somebody four screens deep in a briefing who thinks "why did
 * that happen?" should not have to scroll back to the top to ask. The floating
 * launcher is the one control in the app that is always within reach, and it
 * is deliberately the only one -- a second floating thing would make this a
 * dashboard with widgets.
 *
 * IT LABELS ITSELF. A bare icon bubble in the corner of a page is read as a
 * support chat, which is exactly the wrong expectation to set: people ask
 * support chats to be dismissed, not to explain their data. The words "AI
 * Analyst" are what make it look like a feature.
 *
 * IT HIDES WHEN THE PANEL IS OPEN rather than turning into a close button.
 * The panel already has a close control in its header; a second one that
 * lands in a different place is two answers to one question.
 */
export default function AnalystLauncher({ open, onOpen, filename }) {
  return (
    <button
      type="button"
      className={`launcher ${open ? 'launcher--hidden' : ''}`.trim()}
      onClick={onOpen}
      aria-expanded={open}
      // Not merely invisible: while the panel is open this must leave the tab
      // order too, or a keyboard user tabs from the panel into a button that
      // is not on screen.
      inert={open}
      tabIndex={open ? -1 : undefined}
    >
      <Spark className="launcher__spark" />
      <span className="launcher__label">AI Analyst</span>
      {/* The dataset it will answer about, when there is one. This is the
          difference between a chat button and an analyst: it says up front
          that it already knows what you are looking at. */}
      {filename && <span className="launcher__context">{filename}</span>}
    </button>
  )
}
