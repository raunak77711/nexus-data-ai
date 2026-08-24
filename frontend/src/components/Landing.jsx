import NexusMark from './NexusMark'
import UploadPane from './UploadPane'
import './Landing.css'

/**
 * The first screen: what this is, and the one thing to do about it.
 *
 * The whole screen has one job — a person who has never seen it should know
 * what it does and have somewhere to drop a file within a few seconds. So the
 * hero is left-aligned rather than centred (centred hero + two buttons is the
 * shape of every landing page ever generated), the headline is the promise, and
 * the drop zone is directly beneath it rather than a scroll away.
 *
 * Below that, three sample datasets. They are here because the empty state is
 * where a first-time user decides whether this tool is worth their own data,
 * and making them go and find a CSV before they can see anything is the easiest
 * possible way to lose them.
 */
export default function Landing({
  samples,
  onLoadSample,
  loadingKey,
  onFile,
  uploadStatus,
  uploadError,
  disabled,
}) {
  const busy = uploadStatus === 'uploading'

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-mark" aria-hidden="true">
          <NexusMark size={44} strokeWidth={2.2} />
        </div>

        <h1 id="hero-heading" className="hero-title">
          Upload data.
          <br />
          Discover intelligence.
        </h1>

        <p className="hero-lead">
          NEXUS turns a raw spreadsheet into an interactive world — what is in it,
          what is changing, what looks unusual, and what comes next. No formulas,
          no code, no data science.
        </p>

        <div className="hero-actions">
          {/* An anchor rather than a scroll handler: it works with JavaScript
              disabled, it is focusable and announced correctly, and the browser
              handles the smooth scroll (and the reduced-motion opt-out) itself. */}
          <a className="btn btn-primary hero-cta" href="#upload">
            Upload dataset
          </a>
          <a className="btn btn-secondary hero-cta" href="#samples">
            Explore sample data
          </a>
        </div>
      </section>

      <section className="landing-upload" id="upload" aria-label="Upload your data">
        <UploadPane
          onFile={onFile}
          status={uploadStatus}
          error={uploadError}
          disabled={disabled || busy}
          filename={null}
          fileSize={null}
        />
      </section>

      <section className="samples" id="samples" aria-labelledby="samples-heading">
        <div className="samples-head">
          <span className="eyebrow">Or start with an example</span>
          <h2 id="samples-heading" className="samples-title">
            Three datasets, three kinds of world
          </h2>
        </div>

        <SampleGrid
          samples={samples}
          onLoadSample={onLoadSample}
          loadingKey={loadingKey}
          disabled={disabled || busy}
        />
      </section>
    </div>
  )
}

/**
 * Human-readable descriptions of the bundled samples.
 *
 * The API sends a description of each file written for someone who already
 * knows what a timeseries is ("400 days of revenue with a trend, weekly
 * seasonality, mixed date formats"). That is true, useful, and the wrong first
 * sentence for a person deciding whether to click. These say what the data is
 * ABOUT; the technical description is still shown, underneath, in smaller type.
 */
const SAMPLE_COPY = {
  timeseries: {
    name: 'Daily sales',
    blurb: 'Nearly two years of revenue, day by day, across four regions.',
    shows: 'Trends and forecasting',
  },
  geo: {
    name: 'Air quality sensors',
    blurb: 'Pollution readings from monitoring stations around the UK.',
    shows: 'Maps and locations',
  },
  tabular: {
    name: 'Employee records',
    blurb: 'Salary, experience and satisfaction across six departments.',
    shows: 'Comparisons and distributions',
  },
}

function SampleGrid({ samples, onLoadSample, loadingKey, disabled }) {
  // null means the listing has not come back yet, which is a different state
  // from an empty list and gets a different treatment: placeholders rather
  // than an explanation.
  if (samples === null) {
    return (
      <ul className="sample-grid" aria-busy="true">
        {[0, 1, 2].map((index) => (
          <li key={index} className="sample-card sample-card-loading">
            <span className="skeleton sample-skeleton" />
          </li>
        ))}
      </ul>
    )
  }

  if (samples.length === 0) {
    return (
      <p className="status-note" data-tone="info">
        No example datasets are on the server. Run{' '}
        <code>python scripts/make_samples.py</code> to generate them, or upload
        your own CSV above.
      </p>
    )
  }

  return (
    <ul className="sample-grid">
      {samples.map((sample) => {
        const copy = SAMPLE_COPY[sample.key] ?? {}
        const loading = loadingKey === sample.key

        return (
          <li key={sample.key}>
            <button
              type="button"
              className="sample-card"
              onClick={() => onLoadSample(sample.key)}
              disabled={disabled || Boolean(loadingKey)}
              data-loading={loading ? 'yes' : 'no'}
            >
              <span className="sample-shows eyebrow">{copy.shows ?? 'Example'}</span>
              <span className="sample-name">{copy.name ?? sample.label}</span>
              <span className="sample-blurb">{copy.blurb ?? sample.description}</span>

              <span className="sample-foot">
                <span className="sample-meta tnum">
                  {sample.filename} · {formatBytes(sample.n_bytes)}
                </span>
                <span className="sample-go" aria-hidden="true">
                  {loading ? 'Opening…' : 'Explore →'}
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
