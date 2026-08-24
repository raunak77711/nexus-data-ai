import NexusMark from './NexusMark'
import UploadPane from './UploadPane'
import './Home.css'

/**
 * The first screen. One sentence, one box, three examples, three steps.
 *
 * WHAT THIS REPLACED, and why. The previous landing page led with a two-line
 * display headline, a paragraph of positioning, and two buttons that both
 * scrolled somewhere else on the same page — so the first decision a visitor
 * had to make was between two things that were not the thing they came to do.
 * The upload box was below all of it.
 *
 * Here the upload box IS the page. Everything else is arranged around it in
 * the order somebody actually needs it:
 *
 *   the promise      — one sentence, no jargon, says what they get
 *   the box          — the only real control on the screen
 *   the examples     — for the visitor who has no file to hand
 *   how it works     — three steps, read only by whoever is still unsure
 *
 * The steps are LAST rather than first. Explaining a process before showing
 * the thing is how a simple tool starts feeling like one that needs studying;
 * anybody who understood the box has already used it by then.
 */
export default function Home({
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
    <div className="home">
      <header className="home-head">
        <span className="home-mark" aria-hidden="true">
          <NexusMark size={30} strokeWidth={2.4} />
        </span>
        <span className="home-wordmark">NEXUS</span>
      </header>

      <section className="home-hero">
        <h1 className="home-title">Understand your spreadsheet</h1>
        <p className="home-lead">
          Add a file and get a clear summary, a chart, and answers to your
          questions. No formulas, no setup, nothing to learn.
        </p>
      </section>

      <section className="home-upload" aria-label="Add your file">
        <UploadPane
          onFile={onFile}
          status={uploadStatus}
          error={uploadError}
          disabled={disabled || busy}
          filename={null}
          fileSize={null}
        />
      </section>

      <section className="home-samples" aria-labelledby="samples-heading">
        <h2 id="samples-heading" className="home-samples-title">
          No file handy? Try one of these
        </h2>
        <SampleRow
          samples={samples}
          onLoadSample={onLoadSample}
          loadingKey={loadingKey}
          disabled={disabled || busy}
        />
      </section>

      <section className="home-steps" aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="visually-hidden">
          How it works
        </h2>
        <ol className="step-list">
          <li className="step">
            <span className="step-number" aria-hidden="true">
              1
            </span>
            <span className="step-text">
              <strong>Add your file</strong>
              You pick a file from your computer.
            </span>
          </li>
          <li className="step">
            <span className="step-number" aria-hidden="true">
              2
            </span>
            <span className="step-text">
              <strong>We read it</strong>
              Takes a few seconds. Nothing for you to do.
            </span>
          </li>
          <li className="step">
            <span className="step-number" aria-hidden="true">
              3
            </span>
            <span className="step-text">
              <strong>You get answers</strong>
              A summary, a chart, and a helper you can ask.
            </span>
          </li>
        </ol>
      </section>
    </div>
  )
}

/**
 * The bundled examples, described by what they are ABOUT.
 *
 * The API sends a description written for somebody who already knows what a
 * timeseries is ("400 days of revenue with a trend, weekly seasonality, mixed
 * date formats"). That is accurate and it is the wrong sentence for a person
 * deciding whether to click, so it does not appear on this screen at all —
 * where the old landing page showed it underneath in smaller type, this shows
 * nothing. A technical description nobody on this screen can use is not extra
 * information, it is extra reading.
 */
const SAMPLE_COPY = {
  timeseries: { name: 'Shop sales', blurb: 'Two years of daily sales' },
  geo: { name: 'Air quality', blurb: 'Readings from around the UK' },
  tabular: { name: 'Staff records', blurb: 'Pay and experience by team' },
}

function SampleRow({ samples, onLoadSample, loadingKey, disabled }) {
  // null means the listing has not come back yet, which is a different state
  // from an empty list and gets a different treatment: placeholders rather
  // than an explanation of something that may yet arrive.
  if (samples === null) {
    return (
      <ul className="sample-row" aria-busy="true">
        {[0, 1, 2].map((index) => (
          <li key={index}>
            <span className="skeleton sample-chip-skeleton" />
          </li>
        ))}
      </ul>
    )
  }

  if (samples.length === 0) return null

  return (
    <ul className="sample-row">
      {samples.map((sample) => {
        const copy = SAMPLE_COPY[sample.key] ?? {}
        const loading = loadingKey === sample.key

        return (
          <li key={sample.key}>
            <button
              type="button"
              className="sample-chip"
              onClick={() => onLoadSample(sample.key)}
              disabled={disabled || Boolean(loadingKey)}
            >
              <span className="sample-chip-name">
                {loading ? 'Opening…' : (copy.name ?? sample.label)}
              </span>
              <span className="sample-chip-blurb">{copy.blurb ?? ''}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
