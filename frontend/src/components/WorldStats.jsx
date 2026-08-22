import './WorldStats.css'

/**
 * The numbers behind the world, chosen per archetype.
 *
 * WHY a curated list rather than dumping every key in the stats dict: the dicts
 * carry internal values (the fitted map zoom, the raw slope) that are correct
 * but meaningless to a reader, and a wall of twelve key-value pairs is read as
 * decoration and skipped. Picking six or seven means each one is there for a
 * reason and can be defended.
 *
 * The trend verdict gets its own treatment because it is the only value here
 * that is a CLAIM rather than a measurement -- it comes from a least-squares
 * fit with a dead band, so it is shown with its slope attached rather than as a
 * bare word the reader has to take on trust.
 */
export default function WorldStats({ archetype, stats }) {
  if (!stats || Object.keys(stats).length === 0) return null

  const rows = buildRows(archetype, stats)
  if (rows.length === 0) return null

  return (
    <section className="world-stats panel" aria-labelledby="world-stats-heading">
      <h3 id="world-stats-heading">What the numbers say</h3>

      {archetype === 'timeseries' && stats.trend_direction && (
        <p className="trend" data-direction={stats.trend_direction}>
          <span className="trend-arrow" aria-hidden="true">
            {{ rising: '↗', falling: '↘', flat: '→', unknown: '?' }[stats.trend_direction]}
          </span>
          <span>
            <strong>{stats.trend_direction}</strong>
            {stats.trend_slope_per_period != null && (
              <>
                {' '}— a least-squares fit over every point gives{' '}
                <span className="tnum">{formatNumber(stats.trend_slope_per_period)}</span> per
                period.
              </>
            )}
          </span>
        </p>
      )}

      <dl className="world-stats-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="tnum">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function buildRows(archetype, stats) {
  if (archetype === 'timeseries') {
    return compact([
      ['Mean', formatNumber(stats.mean)],
      ['Min', formatNumber(stats.min)],
      ['Max', formatNumber(stats.max)],
      ['Std dev', formatNumber(stats.std)],
      [
        'Periods',
        stats.n_periods != null
          ? `${stats.n_periods_observed?.toLocaleString() ?? '—'} observed of ${stats.n_periods.toLocaleString()}`
          : null,
      ],
      ['First', formatDate(stats.first_date)],
      ['Last', formatDate(stats.last_date)],
    ])
  }

  if (archetype === 'geo') {
    return compact([
      ['Points mapped', stats.n_points?.toLocaleString()],
      ['Rows dropped', stats.n_rows_dropped?.toLocaleString()],
      [`Mean ${stats.target_col ?? 'value'}`, formatNumber(stats.target_mean)],
      [`Range`, rangeText(stats.target_min, stats.target_max)],
      ['Centre', stats.center ? `${stats.center.lat}, ${stats.center.lon}` : null],
      [
        'Densest cluster',
        stats.densest_cluster
          ? `${stats.densest_cluster.n_points} points near ${round(stats.densest_cluster.lat)}, ${round(stats.densest_cluster.lon)}`
          : null,
      ],
      ['Time filter', stats.time_filter_applied ? 'Applied' : 'None'],
    ])
  }

  const summary = stats.target_summary ?? {}
  return compact([
    ['Measure', stats.target_col],
    ['Values used', stats.n_values?.toLocaleString()],
    ['Excluded', stats.n_excluded?.toLocaleString()],
    ['Mean', formatNumber(summary.mean)],
    ['Median', formatNumber(summary['50%'])],
    ['Std dev', formatNumber(summary.std)],
    ['Range', rangeText(summary.min, summary.max)],
    ['Categories', stats.n_categories ? `${stats.n_categories} in ${stats.entity_col}` : null],
  ])
}

/** Drop pairs whose value never arrived, so the grid has no blank cells. */
function compact(rows) {
  return rows.filter(([, value]) => value != null && value !== '')
}

function rangeText(low, high) {
  if (low == null || high == null) return null
  return `${formatNumber(low)} – ${formatNumber(high)}`
}

function round(value) {
  return typeof value === 'number' ? value.toFixed(3) : value
}

/**
 * Format a number for reading, not for precision.
 *
 * Values in these datasets span revenue in the hundreds and slopes in the
 * thousandths, so a fixed number of decimal places is wrong for one end or the
 * other. The magnitude decides.
 */
function formatNumber(value) {
  if (value == null || Number.isNaN(value)) return null
  const magnitude = Math.abs(value)
  if (magnitude !== 0 && magnitude < 0.01) return value.toExponential(2)
  const decimals = magnitude >= 1000 ? 0 : magnitude >= 10 ? 2 : 3
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  })
}

function formatDate(iso) {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.valueOf())) return iso
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
}
