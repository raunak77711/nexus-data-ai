import Provenance from './Provenance'
import './Recommendations.css'

/**
 * "What should I do about this?" — the only screen in the app that is not
 * reporting a measurement.
 *
 * WHY THE DISCLAIMER IS AT THE TOP AND NOT IN A FOOTNOTE
 * -----------------------------------------------------
 * Everything else in this product is a fact computed from the user's rows.
 * These are inferences a model drew from those facts, and they read exactly
 * like the facts do — same voice, same confidence, same page. That similarity
 * is the risk, and burying the distinction at the bottom in small grey text is
 * how a product ends up with somebody quoting an AI's guess in a board meeting
 * as though it came out of their data.
 *
 * So the label is the first thing on the screen, every card carries a
 * confidence, and the provenance mark on each one is the `suggested` variant —
 * the only mark in the app with a colour in it.
 *
 * WHY THERE MAY BE ONLY ONE. The server discards any recommendation citing a
 * finding that does not exist, or containing a number nobody computed. One
 * traceable suggestion is a better product than four that sound plausible, and
 * a short list here is the check working rather than the feature failing.
 */
export default function Recommendations({ recommendations, onAsk }) {
  if (!recommendations) {
    return <p className="recs__loading">Working out what this suggests…</p>
  }

  const items = recommendations.recommendations ?? []

  return (
    <div className="recs">
      <header className="recs__head">
        <h1 className="recs__title">What this suggests</h1>
        <p className="recs__disclaimer">{recommendations.disclaimer}</p>
      </header>

      {items.length === 0 ? (
        <p className="recs__empty">
          Nothing in this data supports a specific recommendation. That is a
          real answer rather than a gap — the findings describe what happened,
          and what to do about it depends on things this file does not contain.
        </p>
      ) : (
        <ol className="recs__list">
          {items.map((item) => (
            <li key={item.title} className="rec" data-confidence={item.confidence}>
              <div className="rec__head">
                <h2 className="rec__title">{item.title}</h2>
                <span className="rec__confidence">{item.confidence} confidence</span>
              </div>
              <p className="rec__body">{item.body}</p>
              <div className="rec__foot">
                <Provenance kind="suggested" />
                <button
                  type="button"
                  className="rec__ask"
                  onClick={() => onAsk(`About this: ${item.title}. What does the data actually show?`)}
                >
                  Check this against the data
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
