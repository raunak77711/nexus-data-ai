import { useCallback, useRef, useState } from 'react'
import useReveal from '../hooks/useReveal'
import './Home.css'

/**
 * The home page.
 *
 * THE SHAPE OF THE ARGUMENT
 * -------------------------
 * Hero, then a demonstration, then the capabilities, then the sequence. Each
 * section answers the question the previous one raises: "understand your data
 * without knowing how" invites "what does that actually look like", which the
 * preview answers with five findings; that invites "what else", which the
 * capability list answers; and that invites "what do I have to do", which the
 * numbered steps answer. Nothing here is present because home pages have one.
 *
 * THE PREVIEW IS A SPECIMEN, NOT A SCREENSHOT
 * -------------------------------------------
 * The obvious hero image for an analytics product is a picture of its
 * dashboard, and it is the wrong one here: this product's claim is not "we
 * draw charts" -- everything draws charts -- it is "you will be TOLD what is
 * in your file". The characteristic artefact of that claim is a finding: one
 * sentence, with a number in it, carrying a mark saying where the number came
 * from. So the demonstration shows five of those at full size.
 *
 * WHY THE SPECIMEN NUMBERS ARE LABELLED AS AN EXAMPLE. The app's whole
 * discipline is that a number on screen was computed from the reader's rows.
 * The one place that cannot be true is before they have uploaded anything, so
 * the panel says "example" in the same mono voice the real provenance marks
 * use. The device that marks AI wording is the device that marks a mock-up.
 */

/** The pipeline, in the order it runs. Mirrors STAGES in hooks/useAnalysis. */
const PIPELINE = [
  { id: 'upload', label: 'Upload', detail: 'A CSV, up to 200MB. Nothing to configure.' },
  { id: 'understand', label: 'AI understands', detail: 'Types, gaps, ranges, what each column is.' },
  { id: 'insights', label: 'Insights', detail: 'Trends, relationships, outliers, ranked.' },
  { id: 'charts', label: 'Visualizations', detail: 'Only the charts this data earns.' },
  { id: 'ask', label: 'Ask anything', detail: 'In your own words, about your own rows.' },
]

/**
 * The specimen findings.
 *
 * Deliberately mundane -- a shop's sales -- because a more impressive example
 * (genomics, telemetry) would read as a claim about who this is for. The five
 * are five DIFFERENT KINDS of finding on purpose: a trend, a concentration, an
 * anomaly, a quality problem and a relationship. That variety is the actual
 * claim being made, and a list of five trends would not make it.
 */
const FINDINGS = [
  { kind: 'Trend', text: 'Revenue increased 23%' },
  { kind: 'Distribution', text: 'Kathmandu has the highest customer concentration' },
  { kind: 'Anomaly', text: '3 unusual transactions detected' },
  { kind: 'Quality', text: '7.4% of records contain missing values' },
  { kind: 'Relationship', text: 'Customer age and spending show a strong relationship' },
]

/**
 * What the product does.
 *
 * Set as an editorial list rather than a grid of cards. Seven bordered tiles
 * with seven icons is the house style of every B2B page on the internet, and
 * it flattens everything to one weight -- the opposite of what this list
 * means, since the first item IS the product and the last is a convenience.
 */
const FEATURES = [
  {
    id: 'story',
    name: 'AI Data Story',
    line: 'The whole file, explained in a page of sentences you could read out loud.',
  },
  {
    id: 'insights',
    name: 'Automatic Insights',
    line: 'Findings ranked by how much they matter, not by which column came first.',
  },
  {
    id: 'charts',
    name: 'Smart Visualizations',
    line: 'The chart each finding needs, chosen from the data rather than from a menu.',
  },
  {
    id: 'health',
    name: 'Data Health',
    line: 'A score, the problems behind it, and a one-click fix for the fixable ones.',
  },
  {
    id: 'anomaly',
    name: 'Anomaly Detection',
    line: 'The rows that do not belong, each with the reason it was flagged.',
  },
  {
    id: 'nlq',
    name: 'Natural Language Analysis',
    line: 'Ask in a sentence. It runs the calculation and shows you the working.',
  },
  {
    id: 'report',
    name: 'AI Reports',
    line: 'One document, written up and ready to send to somebody who was not here.',
  },
]

/** The four steps, in the user's words rather than the system's. */
const STEPS = [
  { n: '01', label: 'Upload your data', detail: 'Drop a CSV in. No account, no schema, no setup.' },
  { n: '02', label: 'Nexus understands it', detail: 'It reads every column and works out what kind of data this is.' },
  { n: '03', label: 'Discover what matters', detail: 'Findings arrive ranked, each with the evidence behind it.' },
  { n: '04', label: 'Ask anything', detail: 'Follow a thread in plain English until you have your answer.' },
]

export default function Home({
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
  const dragDepth = useRef(0)

  const handleFiles = useCallback(
    (files) => {
      const file = files?.[0]
      if (file) onFile(file)
    },
    [onFile],
  )

  /**
   * Drag counting.
   *
   * `dragleave` fires every time the pointer crosses into a CHILD element, so
   * tracking a boolean makes the dropzone flicker between states as the cursor
   * moves over the label inside it. Counting enter/leave pairs is the standard
   * fix and the only one that survives nested children.
   */
  const onDragEnter = useCallback(
    (event) => {
      event.preventDefault()
      if (disabled) return
      dragDepth.current += 1
      setDragging(true)
    },
    [disabled],
  )

  const onDragLeave = useCallback(() => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }, [])

  const onDrop = useCallback(
    (event) => {
      event.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      if (disabled) return
      handleFiles(event.dataTransfer?.files)
    },
    [disabled, handleFiles],
  )

  const busy = uploadStatus === 'uploading'

  return (
    <div className="home">
      <section className="home__hero">
        {/* Two nested containers, not one: the outer is the page's single
            column and sets the left edge that every section below shares; the
            inner only caps the measure. Centring a narrow hero inside a wide
            page instead -- the obvious version -- puts the headline's left
            edge 100px right of every heading under it, which reads as a
            layout bug rather than as a change of rhythm. */}
        <div className="home__inner">
          <div className="home__hero-inner">
            <p className="eyebrow home__eyebrow">Nexus &middot; AI Data Analyst</p>

            <h1 className="home__headline">
              Understand your data
              <br />
              without knowing how.
            </h1>

            <p className="home__lede">
              Add a spreadsheet and it is read, checked and analysed straight
              away &mdash; then explained back to you in plain sentences, with
              the charts that prove each one. No formulas, no SQL, nothing to
              configure.
            </p>

            <div className="home__actions">
              {/* The dropzone IS the primary action rather than sitting beside
                  one. A button that opens a file picker next to a drop target
                  that also opens a file picker is two controls for one job. */}
              <div
                className={[
                  'dropzone',
                  dragging ? 'dropzone--over' : '',
                  disabled ? 'dropzone--disabled' : '',
                  busy ? 'dropzone--busy' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onDragEnter={onDragEnter}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
              >
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="dropzone__input"
                  id="home-file"
                  disabled={disabled || busy}
                  onChange={(event) => handleFiles(event.target.files)}
                />
                <label className="dropzone__label" htmlFor="home-file">
                  <span className="dropzone__primary">
                    {busy ? 'Reading your file' : 'Upload dataset'}
                  </span>
                  <span className="dropzone__secondary">
                    {busy ? 'This takes a moment.' : 'or drop a CSV here'}
                  </span>
                  <span className="dropzone__drop-hint" aria-hidden="true">
                    Release to analyse
                  </span>
                </label>
              </div>

              <button
                type="button"
                className="home__secondary"
                onClick={onOpenAssistant}
                disabled={disabled}
              >
                Ask the analyst
              </button>
            </div>

            {uploadError && (
              <p className="status-note home__error" data-tone="error" role="alert">
                <span>
                  <strong>That didn&rsquo;t work.</strong> {uploadError}
                </span>
              </p>
            )}

            {samples && samples.length > 0 && (
              <div className="home__samples">
                <span className="home__samples-label">
                  No file to hand? Try one of these
                </span>
                <div className="home__sample-row">
                  {samples.map((sample) => (
                    <button
                      key={sample.key}
                      type="button"
                      className="home__sample"
                      onClick={() => onLoadSample(sample.key)}
                      disabled={disabled || busy}
                    >
                      {loadingKey === sample.key
                        ? 'Loading…'
                        : sample.label ?? sample.key}
                      {/* The listing carries a description and a byte count. The
                          description is the more useful of the two -- "daily
                          sales by region" tells somebody whether this resembles
                          their own file, and "18 kB" does not. */}
                      {sample.description && (
                        <span className="home__sample-meta">{sample.description}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Datasets already on the server. Without this the home page is a
                dead end for a returning user: their files are there, and every
                route back to them would start with uploading something. */}
            {recent.length > 0 && (
              <div className="home__recent">
                <span className="home__samples-label">
                  Or pick up where you left off
                </span>
                <ul className="home__recent-list">
                  {recent.map((dataset) => (
                    <li key={dataset.id}>
                      <button
                        type="button"
                        className="home__recent-item"
                        onClick={() => onOpenDataset(dataset)}
                        disabled={disabled || busy}
                      >
                        <span className="home__recent-name">{dataset.filename}</span>
                        <span className="home__recent-meta">
                          {dataset.n_rows.toLocaleString()} rows
                          {dataset.health_grade ? ` · ${dataset.health_grade}` : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </section>

      <Preview />
      <Features />
      <Steps />
    </div>
  )
}

/* ------------------------------------------------------------- preview -- */

/**
 * The product demonstration: the pipeline on the left, its output on the right.
 *
 * They are side by side rather than stacked because the point being made is
 * that one produces the other. Stacked, the arrow between them is decoration;
 * beside each other, the panel is visibly what the last stage hands over.
 *
 * Both sides stagger in on scroll, the pipeline first, so the eye travels down
 * the steps and then across to the result -- which is the reading order of the
 * claim.
 */
function Preview() {
  const [ref, shown] = useReveal()

  return (
    <section className="preview" ref={ref} data-shown={shown || undefined}>
      <div className="preview__inner">
        <header className="preview__head">
          <p className="eyebrow">What actually happens</p>
          <h2 className="preview__title">
            You add a file. It hands you back what is in it.
          </h2>
        </header>

        <div className="preview__body">
          {/* ------------------------------------------------ pipeline -- */}
          <ol className="pipeline">
            {PIPELINE.map((stage, index) => (
              <li
                key={stage.id}
                className="pipeline__stage"
                style={{ '--i': index }}
              >
                <span className="pipeline__marker" aria-hidden="true">
                  <span className="pipeline__dot" />
                </span>
                <span className="pipeline__text">
                  <span className="pipeline__label">{stage.label}</span>
                  <span className="pipeline__detail">{stage.detail}</span>
                </span>
              </li>
            ))}
          </ol>

          {/* -------------------------------------------------- findings -- */}
          <figure className="findings">
            <div className="findings__bar" aria-hidden="true">
              <span className="findings__chip">nexus</span>
              <span className="findings__file">sales_2024.csv</span>
              <span className="findings__example">example</span>
            </div>

            <div className="findings__body">
              <p className="findings__count">
                AI found <strong>5</strong> important things
              </p>

              <ul className="findings__list">
                {FINDINGS.map((finding, index) => (
                  <li
                    key={finding.text}
                    className="findings__item"
                    style={{ '--i': index }}
                  >
                    <span className="findings__kind">{finding.kind}</span>
                    <span className="findings__text">{finding.text}</span>
                  </li>
                ))}
              </ul>

              <figcaption className="findings__mark">
                AI wording &middot; numbers computed &middot; example data
              </figcaption>
            </div>
          </figure>
        </div>

        <p className="preview__note">
          Every number you are shown is calculated from your rows. The AI writes
          the sentence around it and never the figure inside it &mdash; if it
          introduces one that was not calculated, the sentence is thrown away
          before it reaches you.
        </p>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------ features -- */

/**
 * The capability list.
 *
 * A list, not a grid: seven rows separated by hairlines, each opening on hover
 * to show its one line of detail. The interaction is the layout's argument --
 * a reader scans seven names in two seconds and reads only the one they
 * stopped on, which is how anybody actually reads a feature list anyway.
 *
 * Below the hover breakpoint every detail line is simply shown. A touch device
 * has no hover to reveal with, and a row that has to be tapped to say what it
 * means is a row most people never read.
 */
function Features() {
  const [ref, shown] = useReveal()

  return (
    <section className="features" ref={ref} data-shown={shown || undefined}>
      <div className="features__inner">
        <header className="features__head">
          <p className="eyebrow">Capabilities</p>
          <h2 className="features__title">Seven things it does on its own.</h2>
        </header>

        <ul className="features__list">
          {FEATURES.map((feature, index) => (
            <li key={feature.id} className="feature" style={{ '--i': index }}>
              <span className="feature__index">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className="feature__name">{feature.name}</span>
              <span className="feature__line">{feature.line}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/* --------------------------------------------------------------- steps -- */

/**
 * How it works, in four steps.
 *
 * Numbered because this genuinely is a sequence -- each step happens after the
 * one above it, and the order is information. Numbering an unordered set of
 * features would be decoration; numbering this is not.
 */
function Steps() {
  const [ref, shown] = useReveal()

  return (
    <section className="steps" ref={ref} data-shown={shown || undefined}>
      <div className="steps__inner">
        <header className="steps__head">
          <p className="eyebrow">How it works</p>
          <h2 className="steps__title">Four steps, three of them ours.</h2>
        </header>

        <ol className="steps__list">
          {STEPS.map((step, index) => (
            <li key={step.n} className="step" style={{ '--i': index }}>
              <span className="step__n">{step.n}</span>
              <h3 className="step__label">{step.label}</h3>
              <p className="step__detail">{step.detail}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
