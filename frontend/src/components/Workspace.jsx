import { useEffect } from 'react'
import { scoreBand } from '../lib/score'
import Story from './Story'
import DashboardView from './DashboardView'
import HealthView from './HealthView'
import DataView from './DataView'
import ReportView from './ReportView'
import DatasetsView from './DatasetsView'
import Recommendations from './Recommendations'
import Timeline from './Timeline'
import './Workspace.css'

/**
 * The Analyze page: the shell around one dataset.
 *
 * THE HEADER ANSWERS "WHAT AM I LOOKING AT", THE RAIL ANSWERS "WHERE AM I"
 * ------------------------------------------------------------------------
 * The identity of the dataset — its name, its shape, whether it can be
 * trusted — is the first thing anybody needs on this page and the thing they
 * re-check most often, so it is a sticky strip across the top rather than a
 * block in the corner of the navigation. The rail underneath it carries only
 * destinations. Before this split the filename lived in the rail and the top
 * bar held a single button, which meant the most important fact on the page
 * was the least prominent thing on it.
 *
 * SEVEN DESTINATIONS, AND WHY THAT IS NOT TOO MANY
 * ------------------------------------------------
 * These seven are not features, they are the questions somebody actually
 * arrives with, in the order they arrive in:
 *
 *   Story     what is in this?          (the default, and where 80% will stay)
 *   Charts    show me
 *   Health    can I trust it?
 *   Actions   what should I do?
 *   Rows      let me check
 *   Report    give me something to send
 *   Compare   how does this differ from another file?
 *
 * The test each one passes is that it answers a question in the user's words
 * rather than naming a capability in ours. There is no "Insights" item because
 * "insights" is not a thing anybody wants; there is no "Cleaning" item because
 * cleaning is something you do to a health problem, and it lives where the
 * problems are listed.
 *
 * "Compare" is the global Datasets page's twin and is deliberately named for
 * the job rather than the object: the library lives in the navbar now, so a
 * second item called "Datasets" in here would be two names for two different
 * things.
 *
 * THE RAIL IS NOT COLLAPSIBLE. A collapse control would be a preference to
 * manage, a state to persist and an icon-only mode to design, in exchange for
 * 232px on a screen that has them. Below 900px it becomes a horizontal strip,
 * which is the only place the space genuinely is not there.
 */

const TABS = [
  { id: 'story', label: 'Story', hint: 'What is in this data' },
  { id: 'dashboard', label: 'Charts', hint: 'The charts this data earns' },
  { id: 'health', label: 'Health', hint: 'Problems, and how to fix them' },
  { id: 'actions', label: 'Actions', hint: 'What to do about it' },
  { id: 'data', label: 'Rows', hint: 'The file itself' },
  { id: 'report', label: 'Report', hint: 'One document to send on' },
  { id: 'datasets', label: 'Compare', hint: 'Measure this against another dataset' },
]

export default function Workspace({
  session,
  analysis,
  tab,
  onTab,
  mode,
  onMode,
  onAsk,
  assistantOpen,
  onStartOver,
  onOpenDataset,
  onCleaned,
  onReverted,
}) {
  const sessionId = session.session_id

  // The Actions tab is the only one whose data is not part of the opening run,
  // because it costs a model round trip and most people never open it. Fetched
  // when the tab is, which is the moment it stops being speculative.
  useEffect(() => {
    if (tab === 'actions') analysis.loadRecommendations()
  }, [tab, analysis])

  const health = analysis.health
  const rows = health?.n_rows ?? session.n_rows ?? 0
  const cols = health?.n_cols ?? session.n_cols ?? 0

  return (
    <div className={`workspace ${assistantOpen ? 'workspace--narrowed' : ''}`.trim()}>
      {/* ---------------------------------------------------------- head -- */}
      <header className="wshead">
        <div className="wshead__id">
          <h1 className="wshead__name" title={session.filename}>
            {session.filename}
          </h1>
          <p className="wshead__shape tnum">
            {rows.toLocaleString()} rows &middot; {cols} column{cols === 1 ? '' : 's'}
            {session.is_cleaned && <span className="wshead__flag">cleaned</span>}
          </p>
        </div>

        <div className="wshead__right">
          {/* The health chip, not a second dial: the Story screen already
              carries the full gauge, and this strip's job is to keep the
              number in reach once the reader has scrolled past it. */}
          {health?.score != null && (
            <button
              type="button"
              className="wshead__health"
              onClick={() => onTab('health')}
              data-band={scoreBand(health.score)}
              title="Open the full data health report"
            >
              <span className="wshead__health-label">Health</span>
              <span className="wshead__health-score tnum">{Math.round(health.score)}</span>
              <span className="wshead__health-grade">{health.grade}</span>
              {health.counts?.critical > 0 && (
                <span className="wshead__health-alert">
                  {health.counts.critical} serious
                </span>
              )}
            </button>
          )}

          <button type="button" className="wshead__another" onClick={onStartOver}>
            Add another file
          </button>
        </div>
      </header>

      <div className="workspace__body">
        {/* ---------------------------------------------------------- rail -- */}
        <nav className="rail" aria-label="Sections">
          <ul className="rail__list">
            {TABS.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="rail__item"
                  aria-current={tab === item.id ? 'page' : undefined}
                  onClick={() => onTab(item.id)}
                  title={item.hint}
                >
                  {item.label}
                  {/* The one badge in the navigation: a count of serious data
                      problems. It is here because a person reading findings
                      needs to know their data is broken without having gone
                      looking for it. */}
                  {item.id === 'health' && health?.counts?.critical > 0 && (
                    <span className="rail__badge">{health.counts.critical}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>

          <div className="rail__foot">
            {/* Beginner/Advanced. Two words, no explanation, because the
                change it makes is visible immediately and reversible
                instantly — which is a better teacher than a tooltip. */}
            <div className="mode" role="group" aria-label="Detail level">
              {['beginner', 'advanced'].map((option) => (
                <button
                  key={option}
                  type="button"
                  className="mode__option"
                  aria-pressed={mode === option}
                  onClick={() => onMode(option)}
                >
                  {option === 'beginner' ? 'Simple' : 'Advanced'}
                </button>
              ))}
            </div>
          </div>
        </nav>

        {/* ---------------------------------------------------------- main -- */}
        <div className="workspace__main">
          {/* Keyed on the tab so each view mounts fresh and runs its entrance
              once. Without the key React reuses the subtree and the new view
              simply appears, which on a screen this dense reads as a flicker
              rather than as a change. */}
          <div className="workspace__view" key={tab}>
            {tab === 'story' && (
              <Story
                sessionId={sessionId}
                briefing={analysis.briefing}
                questions={analysis.questions}
                mode={mode}
                onAsk={onAsk}
                onGoToTab={onTab}
              />
            )}

            {tab === 'dashboard' && (
              <DashboardView
                sessionId={sessionId}
                dashboard={analysis.dashboard}
                mode={mode}
              />
            )}

            {tab === 'health' && (
              <HealthView
                sessionId={sessionId}
                health={analysis.health}
                mode={mode}
                onCleaned={onCleaned}
                onReverted={onReverted}
              />
            )}

            {tab === 'actions' && (
              <Recommendations
                recommendations={analysis.recommendations}
                onAsk={onAsk}
              />
            )}

            {tab === 'data' && (
              <DataView sessionId={sessionId} isCleaned={session.is_cleaned} />
            )}

            {tab === 'report' && (
              <ReportView sessionId={sessionId} filename={session.filename} />
            )}

            {tab === 'datasets' && (
              <DatasetsView
                sessionId={sessionId}
                filename={session.filename}
                onOpen={onOpenDataset}
              />
            )}
          </div>

          {/* The timeline sits under every view rather than on a tab of its
              own. It is context, not a destination — nobody navigates TO a
              log — and keeping it visible is what makes the app feel like it
              has been working rather than like it answered once. */}
          {mode === 'advanced' && tab !== 'report' && (
            <Timeline sessionId={sessionId} version={analysis.health} />
          )}
        </div>
      </div>
    </div>
  )
}
