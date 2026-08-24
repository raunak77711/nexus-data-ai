import ChartPanel from './ChartPanel'
import ExplainThis from './ExplainThis'
import './DashboardView.css'

/**
 * The auto-composed dashboard.
 *
 * WHAT THE "WHY THESE CHARTS" NOTE IS DOING AT THE TOP
 * ---------------------------------------------------
 * It is the difference between this page and a template. The server ranked
 * every chart the data could support and built the winners, so the page can say
 * how many it considered and why each one made it — and if it does not say so,
 * an adaptive dashboard and a canned one look identical to the person reading
 * it. The note is short and sits above the grid rather than being a card in it.
 *
 * LAYOUT: the first panel is full width and the rest are a two-up grid. Not
 * decoration — the server returns panels in score order, so the highest-ranked
 * chart is the one most worth looking at, and giving it the full measure is how
 * a page states a priority. Below it the ranking is fine-grained enough that
 * equal sizing is honest.
 */
export default function DashboardView({ sessionId, dashboard, mode }) {
  if (!dashboard) {
    return (
      <div className="dash" aria-busy="true">
        <div className="dash__kpis">
          {[0, 1, 2, 3].map((n) => (
            <div key={n} className="skeleton skeleton--kpi" />
          ))}
        </div>
        <div className="skeleton skeleton--panel" />
        <div className="skeleton skeleton--panel" />
      </div>
    )
  }

  const kpis = dashboard.kpis ?? []
  const panels = dashboard.panels ?? []
  const [lead, ...rest] = panels

  return (
    <div className="dash">
      {kpis.length > 0 && (
        <section className="dash__kpis" aria-label="Headline numbers">
          {kpis.map((kpi) => (
            <article key={kpi.label} className="kpi">
              <p className="kpi__label">{kpi.label}</p>
              <p className="kpi__value">{kpi.value}</p>
              {kpi.note && <p className="kpi__note">{kpi.note}</p>}
              {/* Only measures are worth explaining. "Rows: 400" needs no
                  explanation and offering one would be noise on four out of
                  five cards. */}
              {kpi.kind === 'measure' && (
                <ExplainThis
                  sessionId={sessionId}
                  target="kpi"
                  refId={kpi.label}
                  defaultLevel={mode === 'advanced' ? 'technical' : 'simple'}
                />
              )}
            </article>
          ))}
        </section>
      )}

      {panels.length > 0 ? (
        <>
          <p className="dash__note">{dashboard.note}</p>

          <div className="dash__grid">
            {lead && (
              <ChartPanel panel={lead} sessionId={sessionId} mode={mode} wide />
            )}
            {rest.map((panel) => (
              <ChartPanel
                key={panel.id}
                panel={panel}
                sessionId={sessionId}
                mode={mode}
              />
            ))}
          </div>
        </>
      ) : (
        <p className="dash__empty">
          There is nothing in this file that can be charted. A chart needs at
          least one column of numbers, and this one appears to be all text — the
          findings and the raw rows are still worth a look.
        </p>
      )}
    </div>
  )
}
