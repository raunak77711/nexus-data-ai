/**
 * The NEXUS mark, as a component.
 *
 * The glyph itself is documented in public/favicon.svg and its shared styling
 * lives in base.css under `.nexus-mark`: four nodes at the corners of a square
 * joined bottom-left → top-left → bottom-right → top-right, which is at once
 * the letter N and a four-node graph.
 *
 * WHY IT IS A COMPONENT NOW. It appears in the navbar, the footer and the
 * analyse-page empty state. Three hand-written copies of the same polyline is
 * three chances for one of them to drift, and a logo that is slightly different
 * on one page is a logo nobody trusts.
 *
 * It inherits `currentColor`, so it is coloured by whatever it sits inside
 * rather than by a prop — the same reason the rest of the interface has no
 * colours to pass around.
 */
export default function NexusMark({ size = 22, weight = 2.6, className = '' }) {
  return (
    <svg
      className={`nexus-mark ${className}`.trim()}
      viewBox="0 0 32 32"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <path
        className="mark-link"
        d="M8 24 L8 8 L24 24 L24 8"
        strokeWidth={weight}
      />
      <circle className="mark-node" cx="8" cy="8" r="3" />
      <circle className="mark-node" cx="8" cy="24" r="3" />
      <circle className="mark-node" cx="24" cy="8" r="3" />
      <circle className="mark-node" cx="24" cy="24" r="3" />
    </svg>
  )
}
