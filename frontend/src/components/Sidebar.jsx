import NexusMark from './NexusMark'
import './Sidebar.css'

/**
 * The dashboard's navigation: five destinations, and the dataset you are in.
 *
 * Five, not fifteen. Every item here is a question a person actually has —
 * "what is this?", "let me look", "what did you find?", "what happens next?",
 * "let me just ask" — rather than a name for a piece of machinery. The labels
 * were written from that side of the screen on purpose: nothing here says
 * profile, archetype, anomaly detection or forecast horizon.
 *
 * On a narrow screen the same list becomes a horizontal scroller under the
 * header. It is one <nav> either way, so tab order and screen-reader output do
 * not change with the viewport.
 */

const VIEWS = [
  {
    id: 'overview',
    label: 'Overview',
    hint: 'What is in this data',
    icon: (
      <>
        <rect x="3" y="3" width="7" height="9" rx="1.2" />
        <rect x="14" y="3" width="7" height="5" rx="1.2" />
        <rect x="14" y="12" width="7" height="9" rx="1.2" />
        <rect x="3" y="16" width="7" height="5" rx="1.2" />
      </>
    ),
  },
  {
    id: 'explore',
    label: 'Explore',
    hint: 'Charts and rows',
    icon: (
      <>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <path d="m7 14 4-5 3 3 5-6" />
      </>
    ),
  },
  {
    id: 'insights',
    label: 'Insights',
    hint: 'What NEXUS found',
    icon: (
      <>
        <path d="M12 3a6 6 0 0 0-3.6 10.8c.6.45.9 1.05.9 1.7V17h5.4v-1.5c0-.65.3-1.25.9-1.7A6 6 0 0 0 12 3Z" />
        <path d="M10 21h4" />
      </>
    ),
  },
  {
    id: 'predict',
    label: 'Predict',
    hint: 'What comes next',
    icon: (
      <>
        <path d="M3 17.5 9 11l4 4 8-8.5" />
        <path d="M21 11V6.5H16.5" />
      </>
    ),
  },
]

export default function Sidebar({
  view,
  onViewChange,
  filename,
  rows,
  columns,
  onNewDataset,
  onAskNexus,
  backend,
}) {
  return (
    <nav className="sidebar" aria-label="Sections">
      <a className="sidebar-brand" href="/" aria-label="NEXUS Data AI — home">
        <NexusMark size={22} strokeWidth={2.4} />
        <span className="sidebar-wordmark">NEXUS</span>
      </a>

      <ul className="sidebar-nav">
        {VIEWS.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="sidebar-link"
              aria-current={view === item.id ? 'page' : undefined}
              onClick={() => onViewChange(item.id)}
            >
              <svg
                className="sidebar-icon"
                viewBox="0 0 24 24"
                width="17"
                height="17"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                {item.icon}
              </svg>
              <span className="sidebar-label">{item.label}</span>
            </button>
          </li>
        ))}

        <li>
          {/* Ask NEXUS opens the assistant panel rather than navigating, so it
              is styled as part of the same list but never takes aria-current --
              you are not "on" it, you have opened it. */}
          <button type="button" className="sidebar-link sidebar-ask" onClick={onAskNexus}>
            <span className="sidebar-icon sidebar-spark" aria-hidden="true">
              ✦
            </span>
            <span className="sidebar-label">Ask NEXUS</span>
          </button>
        </li>
      </ul>

      <div className="sidebar-foot">
        <div className="sidebar-dataset">
          <span className="eyebrow">Dataset</span>
          <p className="sidebar-filename" title={filename}>
            {filename}
          </p>
          <p className="sidebar-shape tnum">
            {rows?.toLocaleString()} rows · {columns} columns
          </p>
        </div>

        <button type="button" className="btn btn-secondary sidebar-new" onClick={onNewDataset}>
          New dataset
        </button>

        <p className="sidebar-health" data-state={backend.state}>
          <span className="sidebar-dot" aria-hidden="true" />
          {backend.state === 'up' && `Connected · v${backend.version}`}
          {backend.state === 'checking' && 'Connecting…'}
          {backend.state === 'down' && 'Not connected'}
        </p>
      </div>
    </nav>
  )
}
