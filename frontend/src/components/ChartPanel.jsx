import { useState } from 'react'
import PlotFigure from './PlotFigure'
import ExplainThis from './ExplainThis'
import Provenance from './Provenance'
import './ChartPanel.css'

/**
 * One chart, with the question it answers and the reason it is on the page.
 *
 * WHY THE QUESTION IS THE HEADING AND THE TITLE IS DEMOTED
 * -------------------------------------------------------
 * The server sends both: a title that names what is plotted ("revenue over
 * time, daily") and a question that says why anyone would look ("How has
 * revenue changed over time?"). Leading with the title is the conventional
 * choice and it is the wrong one for this audience. Somebody who does not know
 * what to do with a spreadsheet cannot tell, from "revenue over time", whether
 * this chart is worth their attention; they can tell instantly from the
 * question. So the question is the <h3> and the title becomes the caption
 * underneath it.
 *
 * THE "WHY" LINE is the part of this component that does not exist in other
 * analytics tools, and it is the payoff of the server choosing charts by score
 * rather than from a template. The page can say `channel` splits `revenue`
 * more unevenly than any other grouping, which is a fact about the user's data
 * and the actual reason this chart beat five others. Hiding that would make an
 * adaptive dashboard indistinguishable from a canned one.
 */
export default function ChartPanel({ panel, sessionId, mode = 'beginner', wide = false }) {
  const [showCode, setShowCode] = useState(false)

  const warnings = panel.warnings ?? []

  return (
    <figure className={`panel ${wide ? 'panel--wide' : ''}`.trim()}>
      <figcaption className="panel__head">
        <h3 className="panel__question">{panel.question || panel.title}</h3>
        {panel.title && panel.question && panel.title !== panel.question && (
          <p className="panel__title">{panel.title}</p>
        )}
      </figcaption>

      <div className="panel__figure">
        <PlotFigure figureJson={panel.figure_json} height={wide ? 380 : 300} />
      </div>

      {/* Warnings say what the chart had to do to the data to draw it -- rows
          dropped, points sampled. Kept next to the figure rather than in a log,
          because somebody who does not know 4,000 of their rows were sampled
          will read the chart as the whole truth. */}
      {warnings.length > 0 && (
        <ul className="panel__warnings">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {panel.why && <p className="panel__why">{panel.why}</p>}

      <div className="panel__foot">
        <ExplainThis sessionId={sessionId} target="chart" refId={panel.id} />

        {/* The glass box. Only offered in Advanced mode: a beginner does not
            want pandas and, more to the point, does not need to be shown a
            thing they cannot read in order to trust the chart above it. The
            code is why an expert trusts it, and experts are who Advanced is. */}
        {mode === 'advanced' && panel.code && (
          <button
            type="button"
            className="panel__code-toggle"
            onClick={() => setShowCode((current) => !current)}
            aria-expanded={showCode}
          >
            {showCode ? 'Hide the code' : 'Show the code'}
          </button>
        )}
      </div>

      {showCode && (
        <div className="panel__code">
          <p className="panel__code-note">
            This is the code that drew the chart above — not a description of
            it. Paste it into a notebook with your data loaded as{' '}
            <code>df</code> and it reproduces the figure exactly.
          </p>
          <pre>
            <code>{panel.code}</code>
          </pre>
          <Provenance kind="computed" />
        </div>
      )}
    </figure>
  )
}
