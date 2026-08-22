import './ArchetypeSelect.css'

/**
 * Manual override for the routed archetype.
 *
 * Defaults to whatever the router decided, and says so plainly when the user
 * has moved away from it. WHY the override exists at all, given the router is
 * the feature: a classifier that cannot be overruled is a classifier the user
 * has to trust blindly, which is the opposite of what this project argues for.
 * Letting someone force "tabular" onto timeseries data and see what happens is
 * how they come to understand what the routing actually bought them.
 *
 * Implemented as radio inputs in a <fieldset>, not a custom widget: arrow-key
 * navigation, grouping and the "one of these" semantic all come for free and
 * correctly, and the visual segmented control is pure CSS over real inputs.
 */

const OPTIONS = [
  { value: 'timeseries', label: 'Timeseries' },
  { value: 'geo', label: 'Geo' },
  { value: 'tabular', label: 'Tabular' },
]

export default function ArchetypeSelect({ value, routed, onChange, disabled }) {
  const overridden = routed && value !== routed

  return (
    <div className="archetype">
      <fieldset className="archetype-set" disabled={disabled}>
        <legend className="archetype-legend">World</legend>
        <div className="segmented" role="none">
          {OPTIONS.map((option) => (
            <label
              key={option.value}
              className="segmented-option"
              data-selected={value === option.value ? 'yes' : 'no'}
            >
              <input
                type="radio"
                name="archetype"
                value={option.value}
                checked={value === option.value}
                onChange={() => onChange(option.value)}
              />
              <span>{option.label}</span>
              {routed === option.value && (
                <span className="segmented-routed" title="Chosen by the router" aria-label="routed">
                  ★
                </span>
              )}
            </label>
          ))}
        </div>
      </fieldset>

      {/* aria-live: the note appears without focus moving to it. */}
      <p className="archetype-note" role="status" aria-live="polite">
        {overridden ? (
          <>
            <strong>Overridden.</strong> The router chose <em>{routed}</em>; you are
            viewing <em>{value}</em>.{' '}
            <button type="button" className="archetype-reset" onClick={() => onChange(routed)}>
              Back to routed
            </button>
          </>
        ) : (
          ''
        )}
      </p>
    </div>
  )
}
