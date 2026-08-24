import { scoreBand } from '../lib/score'
import './ScoreDial.css'

/**
 * The health score, as a ring with the number inside it.
 *
 * WHY A RING AND NOT A BAR OR A BADGE
 * -----------------------------------
 * The score is a proportion of a fixed whole — 87 out of 100 — and a ring is
 * the form that states a proportion without needing an axis. A bar would need
 * a scale to be readable; a coloured badge would state the grade and throw the
 * proportion away, which is the interesting half.
 *
 * COLOUR IS CARRYING MEANING HERE, which is why this is one of the very few
 * places in the app that uses it. Everywhere else colour is reserved for facts;
 * a score IS a fact, and the three bands are the same three bands the server
 * grades against. Crucially the number and the grade word are both present, so
 * the colour is redundant rather than load-bearing — the component is fully
 * readable in greyscale and to anyone who cannot distinguish the hues.
 *
 * Drawn with an SVG arc rather than a conic-gradient so the stroke has a real
 * round cap and the geometry is identical in every browser.
 */

const RADIUS = 20
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export default function ScoreDial({ score, size = 52 }) {
  // Clamped rather than trusted: a score outside 0-100 would draw an arc
  // wrapping past its own start, which looks like a rendering bug rather than
  // like bad data.
  const value = Math.max(0, Math.min(100, Number(score) || 0))
  const offset = CIRCUMFERENCE * (1 - value / 100)

  return (
    <span
      className="dial"
      data-band={scoreBand(value)}
      style={{ inlineSize: size, blockSize: size }}
      role="img"
      aria-label={`Data health score ${Math.round(value)} out of 100`}
    >
      <svg viewBox="0 0 48 48" className="dial__svg" aria-hidden="true">
        <circle className="dial__track" cx="24" cy="24" r={RADIUS} />
        <circle
          className="dial__value"
          cx="24"
          cy="24"
          r={RADIUS}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
        />
      </svg>
      <span className="dial__number">{Math.round(value)}</span>
    </span>
  )
}
