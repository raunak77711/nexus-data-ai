import { useCallback, useState } from 'react'
import * as api from '../api'
import PlotFigure from './PlotFigure'
import Provenance from './Provenance'
import ExplainThis from './ExplainThis'
import './Story.css'

/**
 * The briefing. The first thing anyone sees after uploading, and the screen the
 * whole product exists to deliver.
 *
 * THE STRUCTURE IS THE ARGUMENT
 * -----------------------------
 * Summary, then the ranked findings, then what to ask next. Nothing else. In
 * particular there is no chart above the fold, and that is the deliberate
 * choice this screen turns on: a chart asks the reader to do the interpreting,
 * which is the exact task they came here to be spared. The charts are one click
 * away on their own tab, and each finding opens the chart that proves it.
 *
 * FINDINGS ARE CLICKABLE AND OPEN THEIR OWN EVIDENCE
 * --------------------------------------------------
 * A finding that cannot be checked is an assertion. Each point carries a `link`
 * from the server naming what backs it — an insight with a chart spec, a health
 * issue, the data itself — and expanding a point fetches and draws exactly that.
 * Lazily, because five charts nobody asked for is five charts nobody asked for.
 *
 * THE RANKING IS ACROSS SOURCES, NOT WITHIN THEM
 * ----------------------------------------------
 * A serious data-quality problem outranks an interesting trend, because a trend
 * computed from broken data is not a trend. That ordering is done on the server
 * (core/story.py) and this component renders it as given — resorting here would
 * put the two rankings in disagreement.
 */
export default function Story({
  sessionId,
  briefing,
  questions,
  mode,
  onAsk,
  onGoToTab,
}) {
  if (!briefing) {
    return <StorySkeleton />
  }

  const points = briefing.points ?? []

  return (
    <div className="story">
      {/* ------------------------------------------------------- summary -- */}
      <header className="story__head">
        <div className="story__head-main">
          {/* Not "The briefing". The page speaks as the analyst everywhere
              else, and this is the sentence it has been working towards -- so
              it says what it did rather than naming the artefact. */}
          <p className="story__eyebrow">Here&rsquo;s what I found</p>
          <h1 className="story__headline">{briefing.headline}</h1>
          <p className="story__summary">{briefing.summary}</p>
          <Provenance
            kind={briefing.source === 'llm' ? 'worded' : 'computed'}
            className="story__head-mark"
          />
        </div>

        {/* The health score used to be repeated here as a full dial. It has
            moved to the workspace's sticky header, which carries it on every
            tab and keeps it in reach after the reader has scrolled past this
            heading -- two gauges a hundred pixels apart was one gauge and one
            piece of clutter. */}
      </header>

      {/* -------------------------------------------------------- points -- */}
      {points.length > 0 ? (
        <ol className="story__points">
          {points.map((point, index) => (
            <StoryPoint
              key={point.id}
              point={point}
              index={index}
              sessionId={sessionId}
              mode={mode}
              onGoToTab={onGoToTab}
            />
          ))}
        </ol>
      ) : (
        <p className="story__empty">
          Nothing in this file stood out as a trend, a relationship or an
          anomaly. That is itself a finding — the data is flat. The charts and
          the raw rows are still there to look through.
        </p>
      )}

      {/* ----------------------------------------------------- questions -- */}
      {questions?.questions?.length > 0 && (
        <section className="story__ask">
          <h2 className="story__ask-title">Not sure what to ask?</h2>
          <p className="story__ask-lede">
            These are questions this file can actually answer. Every one has been
            checked against your columns.
          </p>
          <div className="story__ask-list">
            {questions.questions.map((question) => (
              <button
                key={question.text}
                type="button"
                className="story__ask-button"
                onClick={() => onAsk(question.text)}
              >
                <span className="story__ask-text">{question.text}</span>
                {question.why && mode === 'advanced' && (
                  <span className="story__ask-why">{question.why}</span>
                )}
              </button>
            ))}
          </div>
          <Provenance
            kind={questions.source === 'llm' ? 'worded' : 'computed'}
            className="story__ask-mark"
          />
        </section>
      )}
    </div>
  )
}

/**
 * One finding, collapsed to its claim and expandable to its evidence.
 *
 * The chart is fetched on expand and then kept, so collapsing and reopening is
 * free. A finding whose link carries no chart spec expands to an explanation
 * only — which is honest: not every finding has a picture, and drawing an
 * unrelated one to fill the space would be worse than the gap.
 */
function StoryPoint({ point, index, sessionId, mode, onGoToTab }) {
  const [open, setOpen] = useState(false)
  const [chart, setChart] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const spec = point.link?.chart

  const expand = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (!next || chart || !spec) return

    setLoading(true)
    setError('')
    try {
      setChart(await api.buildChart(sessionId, spec))
    } catch (caught) {
      setError(caught.message)
    } finally {
      setLoading(false)
    }
  }, [open, chart, spec, sessionId])

  const kind = point.link?.kind

  return (
    <li className="point" data-tone={point.tone}>
      <button
        type="button"
        className="point__main"
        onClick={expand}
        aria-expanded={open}
      >
        {/* Numbered because the list IS ranked — position one is the most
            important thing in the file, and that ordering is information. */}
        <span className="point__rank">{String(index + 1).padStart(2, '0')}</span>

        <span className="point__body">
          <span className="point__label">{point.label}</span>
          <span className="point__title">{point.title}</span>
          <span className="point__detail">{point.body}</span>
        </span>

        <span className="point__chevron" aria-hidden="true">
          <Chevron open={open} />
        </span>
      </button>

      {open && (
        <div className="point__evidence">
          {loading && <p className="point__loading">Drawing the chart behind this…</p>}
          {error && <p className="point__error">{error}</p>}

          {chart?.figure_json && (
            <div className="point__chart">
              <PlotFigure figureJson={chart.figure_json} height={260} />
            </div>
          )}

          {!spec && kind === 'health' && (
            <p className="point__pointer">
              This came out of the data quality checks.{' '}
              <button type="button" className="point__link" onClick={() => onGoToTab('health')}>
                Open the health report
              </button>
            </p>
          )}

          {!spec && kind === 'data' && (
            <p className="point__pointer">
              This describes the shape of the file.{' '}
              <button type="button" className="point__link" onClick={() => onGoToTab('data')}>
                Look at the rows
              </button>
            </p>
          )}

          {point.id.startsWith('insight:') && (
            <ExplainThis
              sessionId={sessionId}
              target="insight"
              refId={point.id.replace(/^insight:/, '')}
              defaultLevel={mode === 'advanced' ? 'technical' : 'simple'}
            />
          )}
          {point.id.startsWith('health:') && point.id !== 'health:score' && (
            <ExplainThis
              sessionId={sessionId}
              target="health_issue"
              refId={point.id.replace(/^health:/, '')}
              defaultLevel={mode === 'advanced' ? 'technical' : 'simple'}
            />
          )}

          <Provenance kind={point.written_by === 'llm' ? 'worded' : 'computed'} />
        </div>
      )}
    </li>
  )
}

function Chevron({ open }) {
  return (
    <svg
      viewBox="0 0 12 12"
      className={`chevron ${open ? 'chevron--open' : ''}`.trim()}
      aria-hidden="true"
    >
      <path
        d="M3 4.5L6 7.5L9 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/**
 * The loading state.
 *
 * Shaped like the content that is coming — one wide summary block, then a
 * column of finding-sized rows — so the page does not jump when the real thing
 * arrives. A centred spinner would be less work and would make the layout
 * appear to change at the moment of load.
 */
function StorySkeleton() {
  return (
    <div className="story" aria-busy="true">
      <div className="skeleton skeleton--eyebrow" />
      <div className="skeleton skeleton--headline" />
      <div className="skeleton skeleton--summary" />
      <div className="story__points-skeleton">
        {[0, 1, 2, 3].map((row) => (
          <div key={row} className="skeleton skeleton--point" />
        ))}
      </div>
    </div>
  )
}
