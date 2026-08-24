import { useCallback, useRef, useState } from 'react'
import './Landing.css'

/**
 * The home page. One sentence, one action, and a demonstration of the output.
 *
 * THE HERO IS A SPECIMEN, NOT A SCREENSHOT
 * ----------------------------------------
 * The obvious hero for an analytics product is a picture of its dashboard, and
 * it is the wrong hero here for a specific reason: this product's claim is not
 * "we draw charts" -- everything draws charts -- it is "you will be TOLD what
 * is in your file". The characteristic artefact of that claim is not a chart,
 * it is a finding: one sentence, with a number in it, carrying a mark saying
 * where the number came from.
 *
 * So the hero is a specimen of exactly that, at full size, assembling itself
 * once on load. It shows the thing the user is about to receive rather than
 * the furniture it will arrive in. It is also honest about being an example,
 * because a fabricated dashboard implying it is the viewer's own data would be
 * the one dishonest pixel on an otherwise scrupulous page.
 *
 * WHY THE SPECIMEN NUMBERS ARE FLAGGED AS AN EXAMPLE. This app's entire
 * discipline is that a number on screen was computed from the reader's rows.
 * The one place that cannot be true is before they have uploaded anything, so
 * the specimen says "example" in the same mono voice the real provenance marks
 * use. The device that marks AI wording is the device that marks a mock-up.
 */

/**
 * The specimen finding.
 *
 * Deliberately mundane: a shop's monthly sales, which is what most people who
 * open this actually have. A more impressive example -- genomics, telemetry --
 * would read as a claim about who the product is for.
 */
const SPECIMEN = {
  eyebrow: 'Example finding',
  title: 'Revenue climbed 23% since March',
  body:
    'Weekly revenue averaged 4,120 in the first third of the period and 5,068 ' +
    'in the last third. The rise is steady rather than driven by one week.',
  mark: 'AI wording · numbers computed',
}

/** What the product does, in the order it does it. A real sequence, so numbered. */
const FLOW = [
  { n: '01', label: 'You add a file', detail: 'CSV, up to 200MB.' },
  { n: '02', label: 'It gets read', detail: 'Types, gaps, duplicates, ranges.' },
  { n: '03', label: 'It gets analysed', detail: 'Trends, relationships, outliers.' },
  { n: '04', label: 'You get told', detail: 'In sentences, with the charts to match.' },
]

export default function Landing({
  onFile,
  samples,
  onLoadSample,
  loadingKey,
  uploadStatus,
  uploadError,
  disabled,
  onOpenAssistant,
  recent = [],
  onOpenDataset,
}) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const handleFiles = useCallback(
    (files) => {
      const file = files?.[0]
      if (file) onFile(file)
    },
    [onFile],
  )

  const onDrop = useCallback(
    (event) => {
      event.preventDefault()
      setDragging(false)
      if (disabled) return
      handleFiles(event.dataTransfer?.files)
    },
    [disabled, handleFiles],
  )

  const busy = uploadStatus === 'uploading'

  return (
    <div className="landing">
      <header className="landing__hero">
        <p className="landing__eyebrow">Nexus · AI data analyst</p>

        <h1 className="landing__headline">
          Understand your data
          <br />
          without knowing how.
        </h1>

        <p className="landing__lede">
          Add a spreadsheet. It gets read, checked and analysed straight away —
          then explained to you in plain sentences. No formulas, no SQL, no
          charts to configure.
        </p>

        <div className="landing__actions">
          {/* The dropzone IS the primary action rather than sitting below one.
              A button that opens a file picker next to a drop target that also
              opens a file picker is two controls for one job. */}
          <div
            className={`dropzone ${dragging ? 'dropzone--over' : ''} ${
              disabled ? 'dropzone--disabled' : ''
            }`.trim()}
            onDragOver={(event) => {
              event.preventDefault()
              if (!disabled) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              className="dropzone__input"
              id="landing-file"
              disabled={disabled || busy}
              onChange={(event) => handleFiles(event.target.files)}
            />
            <label className="dropzone__label" htmlFor="landing-file">
              <span className="dropzone__primary">
                {busy ? 'Reading your file…' : 'Add a CSV file'}
              </span>
              <span className="dropzone__secondary">
                {busy ? 'This takes a moment.' : 'or drop it here'}
              </span>
            </label>
          </div>

          <button
            type="button"
            className="landing__secondary"
            onClick={onOpenAssistant}
            disabled={disabled}
          >
            Ask the analyst first
          </button>
        </div>

        {uploadError && (
          <p className="landing__error" role="alert">
            {uploadError}
          </p>
        )}

        {samples && samples.length > 0 && (
          <div className="landing__samples">
            <span className="landing__samples-label">
              No file to hand? Try one of these
            </span>
            <div className="landing__sample-row">
              {samples.map((sample) => (
                <button
                  key={sample.key}
                  type="button"
                  className="landing__sample"
                  onClick={() => onLoadSample(sample.key)}
                  disabled={disabled || busy}
                >
                  {loadingKey === sample.key ? 'Loading…' : sample.label ?? sample.key}
                  {/* The sample listing carries a description and a byte count,
                      not a row count. The description is the more useful of the
                      two here — "daily sales by region" tells somebody whether
                      this example resembles their own file, and "18 kB" does
                      not. */}
                  {sample.description && (
                    <span className="landing__sample-meta">{sample.description}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Datasets you have already added.
            Without this the landing page is a dead end for a returning user:
            their files are on the server and every route to them lives inside a
            workspace they can only reach by uploading something. */}
        {recent.length > 0 && (
          <div className="landing__recent">
            <span className="landing__samples-label">Or pick up where you left off</span>
            <ul className="landing__recent-list">
              {recent.map((dataset) => (
                <li key={dataset.id}>
                  <button
                    type="button"
                    className="landing__recent-item"
                    onClick={() => onOpenDataset(dataset)}
                    disabled={disabled || busy}
                  >
                    <span className="landing__recent-name">{dataset.filename}</span>
                    <span className="landing__recent-meta">
                      {dataset.n_rows.toLocaleString()} rows
                      {dataset.health_grade ? ` · ${dataset.health_grade}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </header>

      {/* ------------------------------------------------------- specimen -- */}
      <section className="landing__specimen" aria-label="What a finding looks like">
        <article className="specimen">
          <p className="specimen__eyebrow">{SPECIMEN.eyebrow}</p>
          <h2 className="specimen__title">{SPECIMEN.title}</h2>
          <p className="specimen__body">{SPECIMEN.body}</p>
          <p className="specimen__mark">{SPECIMEN.mark}</p>
        </article>

        <p className="landing__specimen-note">
          Every number you are shown is calculated from your rows. AI writes the
          sentence around it and never the figure inside it — if it introduces
          one that was not calculated, the sentence is thrown away before it
          reaches you.
        </p>
      </section>

      {/* ----------------------------------------------------------- flow -- */}
      <section className="landing__flow" aria-label="How it works">
        <ol className="flow">
          {FLOW.map((step) => (
            <li key={step.n} className="flow__step">
              <span className="flow__n">{step.n}</span>
              <span className="flow__label">{step.label}</span>
              <span className="flow__detail">{step.detail}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
