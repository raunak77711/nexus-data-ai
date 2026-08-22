import './EmptyState.css'

/**
 * What the user sees before they have uploaded anything.
 *
 * The empty state is where a first-time visitor decides whether the tool is
 * worth their own data, so it has one job: make the promise concrete and then
 * make it one click away. Hence the three sample loaders -- asking someone to
 * go and find a CSV before they can see anything is the easiest possible way to
 * lose them, and the samples are the same files the test suites run against, so
 * what they see is not a mock-up.
 *
 * The three cards double as an explanation of the product: they ARE the three
 * archetypes, so reading them teaches the routing concept before the router has
 * run once.
 */

const SAMPLE_ICONS = {
  timeseries: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 17.5 8 11l4 3.5 5.5-8" />
      <path d="M17 6.5h4v4" />
      <path d="M3 21h18" />
    </svg>
  ),
  geo: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  ),
  tabular: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9 9.5V20M15 9.5V20" />
    </svg>
  ),
}

export default function EmptyState({ samples, onLoadSample, loadingKey, disabled }) {
  return (
    <section className="empty" aria-labelledby="empty-heading">
      <div className="empty-hero">
        <p className="empty-eyebrow">
          <span className="empty-dot" aria-hidden="true" />
          CSV in, interactive world out
        </p>

        <h1 id="empty-heading" className="empty-tagline">
          Turn raw data into an <em>interactive world</em>
        </h1>

        <p className="empty-lede">
          Drop a spreadsheet and the app profiles every column, picks the right
          kind of visualisation for it, builds it — and shows you the exact Python
          that produced each chart.
        </p>
      </div>

      <div className="empty-samples">
        <h2 className="empty-samples-heading">
          Or start with one of these
          <span className="section-note">the same files the test suites run against</span>
        </h2>

        {samples === null && (
          <ul className="sample-grid" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <li key={index}>
                <div className="skeleton" style={{ height: '132px' }} />
              </li>
            ))}
          </ul>
        )}

        {samples?.length === 0 && (
          <p className="status-note" data-tone="info">
            No sample files on the server. Run{' '}
            <code>python scripts/make_samples.py</code> to generate them.
          </p>
        )}

        {samples?.length > 0 && (
          <ul className="sample-grid">
            {samples.map((sample, index) => (
              <li key={sample.key} style={{ animationDelay: `${index * 60}ms` }}>
                <button
                  type="button"
                  className="sample-card"
                  onClick={() => onLoadSample(sample.key)}
                  disabled={disabled}
                  data-loading={loadingKey === sample.key ? 'yes' : 'no'}
                >
                  <span className="sample-icon" aria-hidden="true">
                    {SAMPLE_ICONS[sample.key]}
                  </span>
                  <span className="sample-label">{sample.label}</span>
                  <span className="sample-desc">{sample.description}</span>
                  <span className="sample-meta">
                    <code>{sample.filename}</code>
                    <span className="tnum">{(sample.n_bytes / 1024).toFixed(0)} KB</span>
                  </span>
                  {loadingKey === sample.key && (
                    <span className="sample-loading" aria-hidden="true" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
