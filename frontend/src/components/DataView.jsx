import { useEffect, useState } from 'react'
import * as api from '../api'
import Provenance from './Provenance'
import './DataView.css'

/**
 * The rows themselves, plus the column profile.
 *
 * WHY THIS SCREEN EXISTS IN A PRODUCT BUILT TO SPARE PEOPLE THE SPREADSHEET
 * ------------------------------------------------------------------------
 * Because trust runs out somewhere. Everything else in the app is a claim about
 * the file, and at some point someone wants to check one against the file
 * itself — most often the moment a finding surprises them. Taking that away
 * would make the analysis unfalsifiable, which is a worse property than being
 * intimidating.
 *
 * So it is here, it is last in the navigation, and it does not try to be a
 * spreadsheet: no editing, no sorting, no paging controls. It is a window, and
 * it says how large a window it is.
 *
 * THE PROFILE TABLE IS THE MORE USEFUL HALF. "What does this column mean and
 * how much of it is missing" answers more questions than fifty rows of values,
 * so it comes first, and the semantic type sits next to the name rather than at
 * the end of a row nobody scrolls to.
 */
export default function DataView({ sessionId, isCleaned }) {
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    // A fetch effect: this IS the synchronisation with an external system,
    // and the request has to leave in the same tick the effect runs.
    // oxlint-disable-next-line react/set-state-in-effect
    setPreview(null)
    setError('')

    api
      .getPreview(sessionId, 60)
      .then((result) => {
        if (!cancelled) setPreview(result)
      })
      .catch((caught) => {
        if (!cancelled) setError(caught.message)
      })

    return () => {
      cancelled = true
    }
    // Re-fetches when the data is cleaned, so the rows on screen are the rows
    // the rest of the app is now analysing rather than the uploaded ones.
  }, [sessionId, isCleaned])

  // The profile arrives WITH the rows rather than from the session, so the two
  // always describe the same frame. After a clean the columns and their types
  // change, and a profile taken from the upload response would be describing
  // the original file directly above rows from the cleaned one.
  const columns = preview?.profile ?? []

  return (
    <div className="data">
      <header className="data__head">
        <h1 className="data__title">The file itself</h1>
        <p className="data__lede">
          {isCleaned
            ? 'This is your cleaned data — the version every chart and finding is computed from. Your original is still on the server and can be downloaded below.'
            : 'Everything else in this app is a claim about these rows. This is where you check one.'}
        </p>
        <div className="data__downloads">
          <a className="data__download" href={api.exportUrl(sessionId)} download>
            Download {isCleaned ? 'the cleaned CSV' : 'as CSV'}
          </a>
          {isCleaned && (
            <a
              className="data__download"
              href={api.exportUrl(sessionId, { original: true })}
              download
            >
              Download the original
            </a>
          )}
        </div>
      </header>

      {/* -------------------------------------------------------- columns -- */}
      <section className="data__section">
        <h2 className="data__section-title">
          {columns.length} column{columns.length === 1 ? '' : 's'}
        </h2>
        <p className="data__section-note">
          “Means” is this app’s reading of what a column is FOR, which is not the
          same as how it is stored. A whole number with six distinct values is a
          category, not a measurement — and treating it as one is the difference
          between a useful chart and a meaningless average.
        </p>

        <div className="data__scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Means</th>
                <th scope="col">Stored as</th>
                <th scope="col">Distinct</th>
                <th scope="col">Missing</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((column) => (
                <tr key={column.name}>
                  <th scope="row" className="table__name">
                    {column.name}
                  </th>
                  <td>
                    <span className="type" data-type={column.semantic_type}>
                      {FRIENDLY_TYPE[column.semantic_type] ?? column.semantic_type}
                    </span>
                  </td>
                  <td className="table__mono">{column.dtype}</td>
                  <td className="table__num">
                    {column.n_unique?.toLocaleString?.() ?? '—'}
                  </td>
                  <td className="table__num">
                    {column.null_pct ? `${column.null_pct}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Provenance kind="computed" />
      </section>

      {/* ----------------------------------------------------------- rows -- */}
      <section className="data__section">
        <h2 className="data__section-title">The first rows</h2>

        {error && <p className="data__error">{error}</p>}
        {!preview && !error && <p className="data__loading">Fetching rows…</p>}

        {preview && (
          <>
            <p className="data__section-note">
              Showing {preview.n_rows_returned.toLocaleString()} of{' '}
              {preview.n_rows_total.toLocaleString()} rows.
              {preview.truncated &&
                ' The rest are on the server — every calculation in this app runs over all of them, not just these.'}
            </p>

            <div className="data__scroll">
              <table className="table table--dense">
                <thead>
                  <tr>
                    <th scope="col" className="table__rownum">
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
                    // eslint-disable-next-line react/no-array-index-key -- row
                    // position IS the identity here; these are file rows in file
                    // order and there is no id to key on.
                    <tr key={index}>
                      <td className="table__rownum">{index}</td>
                      {row.map((cell, cellIndex) => (
                        <td key={preview.columns[cellIndex] ?? cellIndex}>
                          {cell === null || cell === '' ? (
                            <span className="table__empty" title="No value in this cell">
                              —
                            </span>
                          ) : (
                            String(cell)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

/**
 * Semantic types, in words a non-technical reader can use.
 *
 * The server's vocabulary is internal ("geo_lat", "categorical"). Showing it
 * here would leak the implementation into the one screen whose whole job is to
 * let somebody check their own file.
 */
const FRIENDLY_TYPE = {
  numeric: 'a measurement',
  categorical: 'a category',
  datetime: 'a date',
  geo_lat: 'latitude',
  geo_lon: 'longitude',
  text: 'free text',
}
