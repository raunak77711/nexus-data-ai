import './RoutingBanner.css'

/**
 * Which world was chosen, why, and -- unmissably -- WHICH PATH CHOSE IT.
 *
 * The green "AI routed" / amber "rule-based fallback" distinction is the most
 * important single element on the page, and it is not a detail hidden in a
 * tooltip. The project's claim is that the AI is a classifier whose work is
 * always validated and always replaceable by rules; that claim is only honest
 * if the user can see, at a glance, which one actually ran. A tool that quietly
 * lets a fallback pass as an AI decision is overselling itself, and every other
 * honesty guarantee in the app becomes suspect by association.
 *
 * Amber, not red: the fallback is a legitimate, tested, correct path -- not an
 * error. Red would tell the user something is broken when nothing is.
 */

const ARCHETYPE_COPY = {
  timeseries: {
    label: 'Timeseries world',
    blurb: 'A measure tracked over time, with a rolling trend.',
  },
  geo: {
    label: 'Geo world',
    blurb: 'Points on a fitted map, sized and coloured by a measure.',
  },
  tabular: {
    label: 'Tabular world',
    blurb: 'Distribution, group comparison and correlation.',
  },
}

export default function RoutingBanner({ routing }) {
  if (!routing) return null

  const isLlm = routing.source === 'llm'
  const copy = ARCHETYPE_COPY[routing.archetype] ?? {
    label: routing.archetype,
    blurb: '',
  }

  const columns = [
    ['time', routing.time_col],
    ['measure', routing.target_col],
    ['grouped by', routing.entity_col],
    ['latitude', routing.lat_col],
    ['longitude', routing.lon_col],
  ].filter(([, value]) => Boolean(value))

  return (
    <article className="routing" data-source={routing.source}>
      <header className="routing-head">
        <div className="routing-title">
          <h3>{copy.label}</h3>
          <p className="routing-blurb">{copy.blurb}</p>
        </div>

        <span className="badge routing-badge" data-source={routing.source}>
          <span className="routing-dot" aria-hidden="true" />
          {isLlm ? 'AI routed' : 'Rule-based fallback'}
        </span>
      </header>

      <p className="routing-reasoning">{routing.reasoning}</p>

      {columns.length > 0 && (
        <dl className="routing-columns">
          {columns.map(([role, name]) => (
            <div key={role} className="routing-column">
              <dt>{role}</dt>
              <dd>{name}</dd>
            </div>
          ))}
        </dl>
      )}

      {!isLlm && (
        <p className="routing-footnote">
          The language model was unavailable or its answer failed validation, so
          the deterministic rules decided. The result is fully usable — it just
          had no semantic judgement applied to the choice of measure.
        </p>
      )}
    </article>
  )
}
