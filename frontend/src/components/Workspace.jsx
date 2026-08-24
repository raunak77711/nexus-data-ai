import { useEffect } from 'react'
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
 * The shell around a dataset: navigation, the mode toggle, and the open view.
 *
 * SEVEN DESTINATIONS, AND WHY THAT IS NOT TOO MANY
 * ------------------------------------------------
 * The brief says avoid twenty navigation items, and it is right. These seven
 * are not features, they are the questions somebody actually arrives with, in
 * the order they arrive in:
 *
 *   Story     what is in this?          (the default, and where 80% will stay)
 *   Charts    show me
 *   Health    can I trust it?
 *   Actions   what should I do?
 *   Rows      let me check
 *   Report    give me something to send
 *   Datasets  what else do I have?
 *
 * The test each one passes is that it answers a question in the user's words
 * rather than naming a capability in ours. There is no "Insights" item because
 * "insights" is not a thing anybody wants; there is no "Cleaning" item because
 * cleaning is something you do to a health problem, and it lives where the
 * problems are listed.
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
  { id: 'datasets', label: 'Datasets', hint: 'Everything you have added' },
]

export default function Workspace({
  session,
  analysis,
  tab,
  onTab,
  mode,
  onMode,
  onAsk,
  onOpenAssistant,
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

  return (
    <div className={`workspace ${assistantOpen ? 'workspace--narrowed' : ''}`.trim()}>
      {/* ------------------------------------------------------------ rail -- */}
      <nav className="rail" aria-label="Sections">
        <div className="rail__file">
          <p className="rail__filename" title={session.filename}>
            {session.filename}
          </p>
          <p className="rail__shape">
            {(analysis.health?.n_rows ?? session.n_rows ?? 0).toLocaleString()} rows
            {' · '}
            {analysis.health?.n_cols ?? session.n_cols ?? 0} cols
          </p>
        </div>

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
                    problems. It is here because a person reading findings needs
                    to know their data is broken without having gone looking. */}
                {item.id === 'health' && health?.counts?.critical > 0 && (
                  <span className="rail__badge">{health.counts.critical}</span>
                )}
              </button>
            </li>
          ))}
        </ul>

        <div className="rail__foot">
          {/* Beginner/Advanced. Two words, no explanation, because the change
              it makes is visible immediately and reversible instantly — which
              is a better teacher than a tooltip. */}
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

          <button type="button" className="rail__start-over" onClick={onStartOver}>
            Add another file
          </button>
        </div>
      </nav>

      {/* ------------------------------------------------------------ main -- */}
      <div className="workspace__main">
        <header className="workspace__bar">
          <button
            type="button"
            className="workspace__ask"
            onClick={onOpenAssistant}
            aria-expanded={assistantOpen}
          >
            <Spark />
            Ask the analyst
          </button>
        </header>

        <div className="workspace__view">
          {tab === 'story' && (
            <Story
              sessionId={sessionId}
              briefing={analysis.briefing}
              health={analysis.health}
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

        {/* The timeline sits under every view rather than on a tab of its own.
            It is context, not a destination — nobody navigates TO a log — and
            keeping it visible is what makes the app feel like it has been
            working rather than like it answered once. */}
        {mode === 'advanced' && tab !== 'report' && (
          <Timeline sessionId={sessionId} version={analysis.health} />
        )}
      </div>
    </div>
  )
}

function Spark() {
  return (
    <svg viewBox="0 0 16 16" className="workspace__spark" aria-hidden="true">
      <path
        d="M8 1.5 9.3 6.7 14.5 8 9.3 9.3 8 14.5 6.7 9.3 1.5 8 6.7 6.7z"
        fill="currentColor"
      />
    </svg>
  )
}
