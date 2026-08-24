import './Provenance.css'

/**
 * The mark that says how a sentence on screen was produced.
 *
 * WHY THIS COMPONENT IS THE SIGNATURE OF THIS INTERFACE
 * -----------------------------------------------------
 * Every AI product in this category shows you a paragraph and leaves you to
 * guess which parts of it are measurements and which are the model talking.
 * This one can answer that question exactly, because the server enforces the
 * distinction rather than intending it: numbers are computed by pandas, and a
 * model's rewrite is discarded outright if it contains a figure nobody
 * computed (see core/grounding.py). Having built that guarantee, hiding it
 * would be strange. So it is a visible, consistent, typographic device.
 *
 * Three kinds, and they are genuinely different claims:
 *
 *   computed    pandas produced this, wording included. It is a measurement.
 *   worded      pandas produced the numbers; a model wrote the sentence around
 *               them. Every figure in it was checked against the computed set.
 *   suggested   a model's inference. NOT a measurement. The thing a reader
 *               most needs to be able to tell apart, and the reason this
 *               component exists at all.
 *
 * Marked typographically rather than by colour on purpose -- see the
 * --provenance-* tokens for the argument.
 */

const KINDS = {
  computed: {
    label: 'Computed',
    title:
      'Calculated directly from your rows. Both the number and the wording ' +
      'come from the calculation.',
  },
  worded: {
    label: 'AI wording',
    title:
      'The numbers were calculated from your rows; AI wrote the sentence ' +
      'around them. Any figure it introduced that was not calculated is ' +
      'rejected before you see it.',
  },
  suggested: {
    label: 'AI suggestion',
    title:
      'An AI inference from the findings, not a measurement. Worth ' +
      'considering, not worth quoting.',
  },
}

export default function Provenance({ kind = 'computed', className = '' }) {
  const meta = KINDS[kind] ?? KINDS.computed
  return (
    <span
      className={`provenance provenance--${kind} ${className}`.trim()}
      title={meta.title}
    >
      {/* A rule rather than an icon. An icon at this size is a smudge, and a
          badge would make a quiet annotation look like a status pill. */}
      <span className="provenance__rule" aria-hidden="true" />
      {meta.label}
    </span>
  )
}
