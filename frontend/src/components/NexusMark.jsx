/**
 * The NEXUS mark — and, when a dataset is being read, the loading state.
 *
 * THE GLYPH: four nodes at the corners of a square, joined by the path
 * bottom-left → top-left → bottom-right → top-right. That polyline is the
 * letter N. With its vertices drawn it is also a four-node graph. One object,
 * two readings, legible at 16px, and it never needs a second version.
 *
 * WHY THE LOGO IS ALSO THE SPINNER: uploading is the moment the product makes
 * its promise — you hand it a file, it works out what is in there. A generic
 * spinner says "wait"; this says "connecting things up", which is the actual
 * claim. Each of the three real backend stages lights one more segment, so the
 * animation is a progress report rather than a decoration: it cannot run ahead
 * of the work, because `stage` is set from what the network has actually done.
 *
 * `stage` is 0–3. 3 (or `static`) is the finished mark, which is what the
 * sidebar and the hero show.
 */
export default function NexusMark({ size = 24, stage = 3, strokeWidth = 2.5, title }) {
  // The path is drawn as three separate segments rather than one polyline so
  // that a stage can complete a segment exactly. Splitting a single path with
  // stroke-dashoffset would animate a proportion of total length, which is not
  // the same thing and lands the join in the wrong place.
  const segments = [
    'M8 24 L8 8',   // the left upright
    'M8 8 L24 24',  // the diagonal
    'M24 24 L24 8', // the right upright
  ]

  const nodes = [
    { cx: 8, cy: 24, at: 0 },
    { cx: 8, cy: 8, at: 0 },
    { cx: 24, cy: 24, at: 1 },
    { cx: 24, cy: 8, at: 2 },
  ]

  return (
    <svg
      className="nexus-mark"
      viewBox="0 0 32 32"
      width={size}
      height={size}
      role={title ? 'img' : 'presentation'}
      aria-hidden={title ? undefined : 'true'}
      aria-label={title}
    >
      {title && <title>{title}</title>}

      {segments.map((d, index) => (
        <path
          key={d}
          className="mark-link"
          d={d}
          strokeWidth={strokeWidth}
          // A segment that has not been reached yet is present but invisible,
          // so the glyph never changes size as it assembles.
          opacity={index < stage ? 1 : 0}
          style={{ transition: 'opacity var(--dur-slow) var(--ease-draw, ease)' }}
        />
      ))}

      {nodes.map((node) => (
        <circle
          key={`${node.cx}-${node.cy}`}
          className="mark-node"
          cx={node.cx}
          cy={node.cy}
          r={strokeWidth * 1.28}
          opacity={node.at < stage ? 1 : 0.22}
          style={{ transition: 'opacity var(--dur-normal) var(--ease-out)' }}
        />
      ))}
    </svg>
  )
}
