import './Analyzing.css'

/**
 * The screen between "file added" and "here is what I found".
 *
 * WHAT MAKES THIS DIFFERENT FROM A SPINNER WITH NICE WORDS
 * -------------------------------------------------------
 * Every stage here corresponds to a request that is genuinely in flight, and
 * it is marked done when that request answers (see hooks/useAnalysis.js). So
 * on a small file the list completes almost instantly and on a large one the
 * quality check visibly sits there — which is the honest behaviour, and the
 * reason this screen builds trust instead of spending it.
 *
 * The alternative, a timed sequence of reassuring messages, is the standard
 * implementation of this pattern and it is self-defeating: anyone who uploads
 * twice sees the same messages take the same time regardless of the file, and
 * from then on reads every progress indicator in the product as decoration.
 *
 * A stage that has failed is shown as failed rather than quietly skipped. The
 * workspace behind this renders whatever arrived, so a failed stage means one
 * missing section, and saying so here is how the user knows why.
 */
export default function Analyzing({ filename, stages, stageIndex, error }) {
  return (
    <div className="analyzing">
      <div className="analyzing__inner">
        <p className="analyzing__eyebrow">Reading {filename || 'your file'}</p>

        <h1 className="analyzing__headline">Working through your data.</h1>

        <ol className="analyzing__stages">
          {stages.map((stage, index) => {
            const state =
              index < stageIndex ? 'done' : index === stageIndex ? 'active' : 'waiting'
            return (
              <li key={stage.key} className="analyzing__stage" data-state={state}>
                <span className="analyzing__marker" aria-hidden="true">
                  {state === 'done' ? <Tick /> : <span className="analyzing__dot" />}
                </span>
                <span className="analyzing__label">{stage.label}</span>
              </li>
            )
          })}
        </ol>

        {error && (
          <p className="analyzing__error" role="alert">
            {error} — the rest of the analysis carried on, so you will still get
            everything that did work.
          </p>
        )}

        <p className="analyzing__note">
          Nothing here is a guess. Each step is a calculation running over your
          rows right now.
        </p>
      </div>
    </div>
  )
}

function Tick() {
  return (
    <svg viewBox="0 0 12 12" className="analyzing__tick" aria-hidden="true">
      <path
        d="M2.5 6.4l2.3 2.3L9.6 3.9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
