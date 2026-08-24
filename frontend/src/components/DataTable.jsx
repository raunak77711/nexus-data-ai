import './DataTable.css'

/**
 * The actual rows.
 *
 * Charts and statistics are the app's answer to "what is in this file"; they
 * are not a substitute for occasionally seeing the file. A person who has just
 * uploaded a spreadsheet wants to confirm it read their data properly, and no
 * amount of profiling replaces looking.
 *
 * The table scrolls inside its own box rather than widening the page — a data
 * table is the one thing on a page that legitimately has no maximum width, and
 * letting it push the layout sideways breaks every other screen.
 */
export default function DataTable({ preview, loading, error }) {
  if (loading) return <div className="skeleton table-skeleton" />

  if (error) {
    return (
      <p className="status-note" data-tone="error">
        <strong>The rows could not be loaded.</strong> {error}
      </p>
    )
  }

  if (!preview) return null

  return (
    <div className="table-block">
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Dataset rows">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col" className="data-table-num">
                #
              </th>
              {preview.columns.map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, index) => (
              <tr key={index}>
                <th scope="row" className="data-table-num tnum">
                  {index + 1}
                </th>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} data-empty={cell === null ? 'yes' : 'no'}>
                    {cell === null ? '—' : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="table-note tnum">
        Showing {preview.n_rows_returned.toLocaleString()} of{' '}
        {preview.n_rows_total.toLocaleString()} rows
        {preview.truncated && ' — the rest are still used in every calculation'}
      </p>
    </div>
  )
}
