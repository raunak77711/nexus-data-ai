import { useCallback, useEffect, useState } from 'react'
import * as api from '../api'
import PlotFigure from './PlotFigure'
import Provenance from './Provenance'
import ScoreDial from './ScoreDial'
import './ReportView.css'

/**
 * The report: the whole analysis as one document, laid out to be printed.
 *
 * WHY THE PDF IS THE BROWSER'S JOB
 * --------------------------------
 * Generating it server-side would mean a rendering dependency, a font stack and
 * a layout engine that has to agree with the one on screen — three new ways to
 * hand somebody a document that does not match what they approved. The browser
 * already has all three and is already showing them the thing they want. So
 * "Save as PDF" is `window.print()` against a print stylesheet, and what comes
 * out is exactly what was on screen minus the app furniture.
 *
 * SECTION ORDER IS THE SERVER'S DECISION and is rendered as given. In particular
 * data quality comes BEFORE the findings, which is not the conventional order
 * for a business report — the convention buries caveats at the back, and that is
 * how a reader reaches page four believing a number that page nine explains is
 * unreliable.
 */
export default function ReportView({ sessionId, filename }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const generate = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setReport(await api.getReport(sessionId))
    } catch (caught) {
      setError(caught.message)
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  // The report is not fetched on mount. It is the most expensive call in the
  // app — it needs every analysis to exist — and it belongs to an explicit
  // "generate" action rather than to opening a tab.
  useEffect(() => {
    // Clearing a report belonging to a dataset the user has navigated away
    // from. There is no event to hang this on: the session changed elsewhere.
    // oxlint-disable-next-line react/set-state-in-effect
    setReport(null)
    setError('')
  }, [sessionId])

  if (!report) {
    return (
      <div className="report__intro">
        <h1 className="report__intro-title">Generate a report</h1>
        <p className="report__intro-lede">
          Everything found in {filename} as one document: what the data is, how
          much of it can be trusted, what was found, the charts behind it, and
          what might be worth doing. Ready to print or save as a PDF.
        </p>
        {error && (
          <p className="report__error" role="alert">
            {error}
          </p>
        )}
        <button
          type="button"
          className="button button--primary"
          onClick={generate}
          disabled={loading}
        >
          {loading ? 'Putting it together…' : 'Generate report'}
        </button>
        {loading && (
          <p className="report__intro-note">
            Anything you have already looked at is reused, so this is quick if
            you have been around the app.
          </p>
        )}
      </div>
    )
  }

  return (
    <article className="report">
      <header className="report__head">
        <div className="report__head-text">
          <h1 className="report__title">{report.title}</h1>
          <p className="report__subtitle">
            {report.subtitle} · {report.generated_display}
          </p>
        </div>
        <div className="report__head-actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => window.print()}
          >
            Save as PDF
          </button>
          <a
            className="button button--quiet"
            href={api.exportUrl(sessionId)}
            download
          >
            Export the data
          </a>
        </div>
      </header>

      {report.sections.map((section) => (
        <Section key={section.kind} section={section} />
      ))}

      <footer className="report__foot">
        <p>
          Every figure in this report was calculated from the uploaded file.
          Where AI wrote a sentence, the numbers inside it were checked against
          the calculation before it was shown. Recommendations are AI
          suggestions and are labelled as such.
        </p>
      </footer>
    </article>
  )
}

/** One section, dispatched on `kind` rather than on its title. */
function Section({ section }) {
  return (
    <section className="report__section" data-kind={section.kind}>
      <h2 className="report__section-title">{section.title}</h2>
      {renderBody(section)}
    </section>
  )
}

function renderBody(section) {
  switch (section.kind) {
    case 'summary':
      return (
        <>
          <p className="report__lede">{section.body}</p>
          {section.highlights?.length > 0 && (
            <ul className="report__highlights">
              {section.highlights.map((item) => (
                <li key={item.title}>
                  <strong>{item.title}</strong>
                  <span>{item.body}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )

    case 'overview':
      return (
        <>
          <div className="report__stats">
            <Stat label="Rows" value={section.n_rows?.toLocaleString()} />
            <Stat label="Columns" value={section.n_cols} />
            <Stat label="Shape" value={section.archetype} />
          </div>
          {section.reasoning && (
            <p className="report__note">
              {section.reasoning}{' '}
              <em>
                (decided{' '}
                {section.routed_by === 'llm' ? 'by AI' : 'from the column types'})
              </em>
            </p>
          )}
          {section.kpis?.length > 0 && (
            <div className="report__kpis">
              {section.kpis.map((kpi) => (
                <div key={kpi.label} className="report__kpi">
                  <span className="report__kpi-label">{kpi.label}</span>
                  <span className="report__kpi-value">{kpi.value}</span>
                  {kpi.note && <span className="report__kpi-note">{kpi.note}</span>}
                </div>
              ))}
            </div>
          )}
          <table className="report__table">
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Means</th>
                <th scope="col">Distinct</th>
                <th scope="col">Missing</th>
              </tr>
            </thead>
            <tbody>
              {section.columns.map((column) => (
                <tr key={column.name}>
                  <th scope="row">{column.name}</th>
                  <td>{column.kind}</td>
                  <td>{column.unique?.toLocaleString?.() ?? '—'}</td>
                  <td>{column.missing_pct ? `${column.missing_pct}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )

    case 'quality':
      return (
        <>
          <div className="report__quality">
            {section.score != null && <ScoreDial score={section.score} size={64} />}
            <div>
              <p className="report__quality-grade">{section.grade}</p>
              <p className="report__lede">{section.verdict}</p>
            </div>
          </div>
          {section.issues?.length > 0 && (
            <ul className="report__issues">
              {section.issues.map((issue) => (
                <li key={issue.title} data-severity={issue.severity}>
                  <strong>{issue.title}</strong>
                  <span>{issue.detail}</span>
                  <span className="report__issue-why">{issue.why}</span>
                </li>
              ))}
            </ul>
          )}
          {section.clean?.length > 0 && (
            <p className="report__note">
              Checks that passed: {section.clean.map((c) => c.title).join(', ')}.
            </p>
          )}
        </>
      )

    case 'findings':
      return (
        <>
          {section.summary && <p className="report__lede">{section.summary}</p>}
          <ol className="report__findings">
            {section.findings.map((finding) => (
              <li key={finding.headline}>
                <h3>{finding.headline}</h3>
                <p>{finding.detail}</p>
                <p className="report__finding-why">{finding.why}</p>
              </li>
            ))}
          </ol>
        </>
      )

    case 'charts':
      return (
        <>
          {section.note && <p className="report__note">{section.note}</p>}
          {section.charts.map((chart) => (
            <figure key={chart.id} className="report__figure">
              <figcaption>
                <h3>{chart.question || chart.title}</h3>
                {chart.why && <p>{chart.why}</p>}
              </figcaption>
              <PlotFigure figureJson={chart.figure_json} height={300} />
              {chart.warnings?.length > 0 && (
                <p className="report__warning">{chart.warnings.join(' ')}</p>
              )}
            </figure>
          ))}
        </>
      )

    case 'anomalies':
      return (
        <>
          <p className="report__note">{section.note}</p>
          <ul className="report__anomalies">
            {section.anomalies.map((anomaly) => (
              <li key={anomaly.headline}>
                <strong>{anomaly.headline}</strong>
                <span>{anomaly.detail}</span>
              </li>
            ))}
          </ul>
        </>
      )

    case 'recommendations':
      return (
        <>
          <p className="report__disclaimer">{section.disclaimer}</p>
          <ol className="report__recommendations">
            {section.recommendations.map((rec) => (
              <li key={rec.title}>
                <h3>{rec.title}</h3>
                <p>{rec.body}</p>
                <span className="report__confidence">
                  confidence: {rec.confidence}
                </span>
              </li>
            ))}
          </ol>
          <Provenance kind="suggested" />
        </>
      )

    case 'conclusion':
      return <p className="report__lede">{section.body}</p>

    default:
      return null
  }
}

function Stat({ label, value }) {
  return (
    <div className="report__stat">
      <span className="report__stat-label">{label}</span>
      <span className="report__stat-value">{value ?? '—'}</span>
    </div>
  )
}
