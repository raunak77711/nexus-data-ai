import NexusMark from './NexusMark'
import './NoDataset.css'

/**
 * The Analyze page with nothing open.
 *
 * WHY THIS IS NOT A REDIRECT TO HOME. Somebody clicking "Analyze" in the
 * navbar has said what they want to do; bouncing them to the home page
 * answers a question they did not ask and loses the intent. This screen keeps
 * them where they aimed and puts the two ways forward in front of them —
 * upload something, or open something that is already there.
 *
 * It is deliberately quiet. An empty state that fills the space with
 * illustration and copy is compensating for having nothing to say; three
 * sentences and two buttons is the whole of what is true here.
 */
export default function NoDataset({ onUpload, onRoute, hasDatasets, disabled, error }) {
  return (
    <div className="nodata">
      <NexusMark size={40} className="nodata__mark" />

      <h1 className="nodata__title">
        {error ? 'Something went wrong.' : 'Nothing open yet.'}
      </h1>

      {/* An upload that failed lands here, because that is where the user
          already is — bouncing them back to the home page to read the reason
          would be a second thing going wrong. The message from the server is
          already a sentence fit to show; see api.js. */}
      <p className="nodata__lede">
        {error ||
          'This is where your analysis appears — the story of the file, the ' +
            'findings, the charts and the health report. Add a dataset and it ' +
            'starts on its own.'}
      </p>

      <div className="nodata__actions">
        <button
          type="button"
          className="btn btn-primary nodata__cta"
          onClick={onUpload}
          disabled={disabled}
        >
          {error ? 'Try again' : 'Upload dataset'}
        </button>

        {/* Only offered when it leads somewhere. A button to a library the
            user has never put anything in is a button to an empty room. */}
        {hasDatasets && (
          <button
            type="button"
            className="btn btn-secondary nodata__cta"
            onClick={() => onRoute('datasets')}
          >
            Open an existing one
          </button>
        )}
      </div>

      {disabled && (
        <p className="nodata__offline">
          The analysis service is not responding, so uploading is paused. This
          page reconnects on its own.
        </p>
      )}
    </div>
  )
}
