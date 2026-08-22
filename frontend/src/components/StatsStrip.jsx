import './StatsStrip.css'

/**
 * The four numbers that describe the upload, before any world is built.
 *
 * Deliberately derived from the profile rather than from a separate endpoint:
 * every value here is already in the payload the upload returned, and asking
 * the server again for numbers it has already sent is how two parts of a UI
 * come to disagree with each other.
 *
 * The date span is included only when there is a datetime column, rather than
 * being shown as "n/a". An empty slot in a row of four is more honest than a
 * placeholder, and it keeps the row from implying a measurement that was never
 * taken.
 */
export default function StatsStrip({ profile, filename }) {
  if (!profile) return null

  const dateColumn = profile.columns.find(
    (column) => column.semantic_type === 'datetime' && column.min_date && column.max_date,
  )

  const items = [
    { key: 'rows', label: 'Rows', value: profile.n_rows.toLocaleString() },
    { key: 'cols', label: 'Columns', value: profile.n_cols.toLocaleString() },
    {
      key: 'numeric',
      label: 'Numeric',
      value: profile.n_numeric.toLocaleString(),
      note: `of ${profile.n_cols}`,
    },
  ]

  if (dateColumn) {
    items.push({
      key: 'span',
      label: 'Date span',
      value: formatSpan(dateColumn.min_date, dateColumn.max_date),
      note: dateColumn.name,
    })
  } else if (profile.has_geo) {
    items.push({ key: 'geo', label: 'Coordinates', value: 'Present', note: 'lat + lon' })
  }

  return (
    <dl className="stats-strip">
      {items.map((item, index) => (
        <div
          key={item.key}
          className="stat"
          /* A short stagger so the strip assembles left to right instead of
             appearing as one block. 40ms apart is below the threshold at which
             it reads as a queue, but enough to feel built rather than pasted. */
          style={{ animationDelay: `${index * 40}ms` }}
        >
          <dt>{item.label}</dt>
          <dd>
            <span className="stat-value tnum">{item.value}</span>
            {item.note && <span className="stat-note">{item.note}</span>}
          </dd>
        </div>
      ))}
      {filename && (
        <div className="stat stat-file" style={{ animationDelay: `${items.length * 40}ms` }}>
          <dt>File</dt>
          <dd>
            <span className="stat-file-name" title={filename}>{filename}</span>
          </dd>
        </div>
      )}
    </dl>
  )
}

/** "Jan 2023 → Feb 2024 (400 days)" from two ISO strings. */
function formatSpan(minIso, maxIso) {
  const start = new Date(minIso)
  const end = new Date(maxIso)
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return '—'

  const days = Math.round((end - start) / 86_400_000)
  const format = new Intl.DateTimeFormat(undefined, { month: 'short', year: 'numeric' })
  return `${format.format(start)} → ${format.format(end)}`.concat(
    days > 0 ? ` · ${days.toLocaleString()}d` : '',
  )
}
