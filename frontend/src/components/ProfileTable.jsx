import './ProfileTable.css'

/**
 * One row per column of the uploaded dataset.
 *
 * This is a real <table> with <caption>, <thead>, <th scope="col"> and a row
 * header per column name. It is tabular data, so it is a table -- the div-grid
 * version looks identical and is unnavigable with a screen reader, which cannot
 * then announce "column: salary, semantic type: numeric" as it moves across.
 */

/** Human labels for the profiler's semantic types, plus the CSS modifier. */
const TYPE_META = {
  datetime: { label: 'date', tone: 'datetime' },
  numeric: { label: 'numeric', tone: 'numeric' },
  categorical: { label: 'category', tone: 'categorical' },
  geo_lat: { label: 'latitude', tone: 'geo' },
  geo_lon: { label: 'longitude', tone: 'geo' },
  text: { label: 'text', tone: 'text' },
}

export default function ProfileTable({ profile }) {
  if (!profile?.columns?.length) return null

  const rows = profile.columns

  return (
    <div className="profile-scroll">
      <table className="profile-table">
        <caption className="visually-hidden">
          Detected type, pandas dtype, distinct values and missing data for each
          of the {rows.length} columns.
        </caption>
        <thead>
          <tr>
            <th scope="col">Column</th>
            <th scope="col">Detected as</th>
            <th scope="col">dtype</th>
            <th scope="col" className="numeric-col">Unique</th>
            <th scope="col" className="missing-col">Missing</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((column) => {
            const meta = TYPE_META[column.semantic_type] ?? {
              label: column.semantic_type,
              tone: 'text',
            }
            return (
              <tr key={column.name}>
                <th scope="row" className="profile-name" title={column.name}>
                  {column.name}
                </th>
                <td>
                  {/* The type is spelled out as text, not signalled by colour
                      alone -- colour is reinforcement, never the only channel. */}
                  <span className="badge type-badge" data-type={meta.tone}>
                    {meta.label}
                  </span>
                </td>
                <td className="profile-dtype">{column.dtype}</td>
                <td className="numeric-col tnum">{column.n_unique.toLocaleString()}</td>
                <td className="missing-col">
                  <NullBar pct={column.null_pct} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Missing-data proportion as a bar plus the number.
 *
 * WHY a bar rather than the number alone: "3.2%" and "31.8%" are four
 * characters apart and take a moment to compare; a filled bar is comparable at
 * a glance down the column, which is exactly the question a reader has of this
 * table ("which column is the problem one?").
 *
 * A zero-null column deliberately shows an empty track rather than nothing at
 * all -- an absent bar and a zero-length bar look the same, and the reader
 * should be able to tell "no missing values" from "not measured".
 */
function NullBar({ pct }) {
  const clamped = Math.max(0, Math.min(100, pct ?? 0))
  const tone = clamped === 0 ? 'none' : clamped < 5 ? 'low' : clamped < 25 ? 'mid' : 'high'

  return (
    <span className="null-bar" data-tone={tone}>
      <span
        className="null-bar-track"
        role="img"
        aria-label={`${clamped.toFixed(1)} percent missing`}
      >
        {/* A hairline minimum so a 0.1% null rate is still visible. */}
        <span
          className="null-bar-fill"
          style={{ width: clamped === 0 ? '0' : `${Math.max(clamped, 2)}%` }}
        />
      </span>
      <span className="null-bar-value tnum" aria-hidden="true">
        {clamped === 0 ? '—' : `${clamped.toFixed(1)}%`}
      </span>
    </span>
  )
}
