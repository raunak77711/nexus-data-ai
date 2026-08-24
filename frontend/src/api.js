/**
 * Every HTTP call the app makes, in one module.
 *
 * WHY this is not spread through the components: a component that fetches is a
 * component that cannot be reasoned about without knowing the server. Keeping
 * the calls here means the base URL, the error shape and the "backend is down"
 * distinction are decided once, and a component's job is reduced to rendering
 * one of three states -- loading, error, data.
 *
 * The backend guarantees a single error shape, `{ detail: "<sentence>" }`, for
 * every failure at every status code. That guarantee is what lets `request()`
 * below have exactly one error branch instead of one per endpoint.
 */

// Overridable so the Docker compose service can point at the `backend` host
// instead of localhost without editing source. Vite inlines this at build time.
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

/**
 * An error that already carries a message fit to show a user.
 *
 * `status` is kept separate from the message because the UI treats some codes
 * differently: a 404 means the session expired and the remedy is to re-upload,
 * whereas a 500 means retrying might work. `offline` marks the case where the
 * request never reached a server at all.
 */
export class ApiError extends Error {
  constructor(message, { status = 0, offline = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.offline = offline
  }
}

/**
 * Fetch wrapper: one place that turns any failure into an ApiError.
 *
 * A `fetch` rejection and a 500 response are completely different events -- the
 * first means nothing is listening on the port, the second means the server
 * answered and is broken -- and telling a user "something went wrong" for both
 * is how a five-second fix becomes a twenty-minute one. They are distinguished
 * here and phrased differently.
 */
async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new ApiError(
      'Cannot reach the API. Is the backend running on http://localhost:8000?',
      { offline: true },
    )
  }

  if (!response.ok) {
    // A failing response should carry our JSON error shape, but a proxy or a
    // crash before the handlers run can produce HTML or nothing at all -- so
    // parsing the body is itself allowed to fail.
    let detail = `Request failed with status ${response.status}.`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* keep the status-code fallback */
    }
    throw new ApiError(detail, { status: response.status })
  }

  // A 204 has no body at all, and `response.json()` on an empty body throws a
  // SyntaxError -- not an ApiError, so it would escape every caller's error
  // handling and surface as an unhandled rejection on a request that actually
  // SUCCEEDED. DELETE /datasets/{id} is the endpoint that returns one.
  if (response.status === 204) return null

  return response.json()
}

/** Is the API reachable, and how many sessions does it hold? */
export function getHealth() {
  return request('/health')
}

/**
 * Upload a CSV.
 *
 * No Content-Type header is set on purpose: the browser has to generate the
 * multipart boundary itself, and setting the header by hand produces a request
 * with a boundary-less content type that the server cannot parse.
 */
export function uploadCsv(file) {
  const body = new FormData()
  body.append('file', file)
  return request('/upload', { method: 'POST', body })
}

/** The bundled example datasets that are present on the server's disk. */
export function listSamples() {
  return request('/samples')
}

/** Load one bundled sample; returns the same shape as an upload. */
export function loadSample(key) {
  return request(`/samples/${encodeURIComponent(key)}`, { method: 'POST' })
}

/** The archetype decision, including whether the AI or the rules made it. */
export function getRoute(sessionId) {
  return request(`/route/${encodeURIComponent(sessionId)}`)
}

/**
 * Build a world.
 *
 * `params` is passed through as-is; the server ignores the keys the chosen
 * archetype does not use, so the caller never has to strip stale controls.
 */
export function buildWorld(sessionId, archetype, params = {}) {
  return request(`/world/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ archetype, params }),
  })
}

/** Fit and score a forecast over the routed time/target pair. */
export function runForecast(sessionId, horizon = 14) {
  return request(`/forecast/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ horizon }),
  })
}

/**
 * Ask the chat bubble's assistant anything, with or without a dataset.
 *
 * `sessionId` is optional and that is the point: this is the one call the home
 * page can make, before anything has been uploaded. The server decides which
 * assistant answers — the calculator for questions about the data, the guide
 * for questions about the app — and says which one did in `about`.
 *
 * Note it never 404s on an unknown session. Somebody whose upload has just
 * expired is exactly the person who still needs the helper to answer.
 */
export function askAssistant(message, history = [], sessionId = null) {
  return request('/assistant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history, session_id: sessionId }),
  })
}

/** Ask the grounded assistant a question about the current dataset. */
export function sendChat(sessionId, message, history = []) {
  return request(`/chat/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })
}

/** Everything NEXUS found in the dataset, as plain-language cards. */
export function getInsights(sessionId) {
  return request(`/insights/${encodeURIComponent(sessionId)}`)
}

/**
 * Render one chart from a structured spec.
 *
 * The spec is a small object naming a chart type and some columns — never code.
 * It comes from an insight card's `action`, an assistant answer's `action`, or
 * a control the user changed, and the server validates every field of it
 * against the dataset before drawing anything.
 */
export function buildChart(sessionId, spec) {
  return request(`/chart/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(spec),
  })
}

/** Which columns a what-if may move, and what to start from. */
export function getSimulateOptions(sessionId) {
  return request(`/simulate/${encodeURIComponent(sessionId)}/options`)
}

/** Project the effect of moving one measure by a percentage. */
export function simulate(sessionId, { pctChange, target = null, driver = null }) {
  return request(`/simulate/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pct_change: pctChange, target, driver }),
  })
}

/** The first rows of the dataset, for looking at the actual file. */
export function getPreview(sessionId, limit = 50) {
  return request(`/preview/${encodeURIComponent(sessionId)}?limit=${limit}`)
}

/* ---------------------------------------------------------------------------
 * The autonomous analysis.
 *
 * These are the calls the app makes WITHOUT being asked. Fired the moment an
 * upload lands, they are what turns "I uploaded a CSV, now what" into "the AI
 * already read it". Each is separate rather than bundled so the page can fill
 * in as each finishes -- and so the activity indicator has real stages to
 * report instead of one spinner over one long request.
 * ------------------------------------------------------------------------- */

/** The briefing: what this dataset is, and the five things that matter in it. */
export function getBriefing(sessionId) {
  return request(`/briefing/${encodeURIComponent(sessionId)}`)
}

/** The auto-composed dashboard: headline numbers and the charts this data earns. */
export function getDashboard(sessionId) {
  return request(`/dashboard/${encodeURIComponent(sessionId)}`)
}

/** The data quality report: a score out of 100 and every issue behind it. */
export function getHealthReport(sessionId) {
  return request(`/health-report/${encodeURIComponent(sessionId)}`)
}

/** Suggested next steps. Always AI-generated, always labelled as suggestion. */
export function getRecommendations(sessionId) {
  return request(`/recommendations/${encodeURIComponent(sessionId)}`)
}

/** Questions this dataset can answer, for somebody who does not have any. */
export function getQuestions(sessionId) {
  return request(`/questions/${encodeURIComponent(sessionId)}`)
}

/** What the server actually did to this dataset, with real timestamps. */
export function getTimeline(sessionId) {
  return request(`/timeline/${encodeURIComponent(sessionId)}`)
}

/**
 * Explain one thing on screen, simply or technically.
 *
 * `ref` names something the SERVER computed -- an insight id, an issue id, a
 * panel id. Deliberately not a free-form description of what is on screen: the
 * explanation is checked against the numbers the server holds, and a client
 * that supplied its own figures would be supplying both sides of that check.
 */
export function explain(sessionId, { target, ref, level = 'simple' }) {
  return request(`/explain/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, ref, level }),
  })
}

/* --------------------------------------------------------------- cleaning -- */

/** What a clean WOULD change. Changes nothing. */
export function planClean(sessionId, issueIds = null) {
  return request(`/clean/${encodeURIComponent(sessionId)}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ issue_ids: issueIds }),
  })
}

/**
 * Apply the approved repairs.
 *
 * `issueIds` of null means every fixable issue; an empty array means none.
 * Those are different requests and the server treats them differently, so the
 * default here is null rather than [] on purpose.
 */
export function applyClean(sessionId, issueIds = null) {
  return request(`/clean/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ issue_ids: issueIds }),
  })
}

/** Put the dataset back exactly as it was uploaded. */
export function revertClean(sessionId) {
  return request(`/clean/${encodeURIComponent(sessionId)}/revert`, {
    method: 'POST',
  })
}

/**
 * The download URL for the dataset as CSV.
 *
 * A URL rather than a fetch, because the browser downloading a file directly
 * is the whole point -- fetching it into memory to re-offer it as a blob would
 * buy nothing and would break for a large file.
 */
export function exportUrl(sessionId, { original = false } = {}) {
  const query = original ? '?original=true' : ''
  return `${BASE}/export/${encodeURIComponent(sessionId)}${query}`
}

/* --------------------------------------------------------------- datasets -- */

/** Every dataset the server is holding, most recently opened first. */
export function listDatasets() {
  return request('/datasets')
}

/** Forget a dataset completely, including the stored copy of the file. */
export function deleteDataset(sessionId) {
  // Resolves to null: the endpoint answers 204, which request() maps to null
  // rather than trying to parse an empty body as JSON.
  return request(`/datasets/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/** Compare this dataset against another stored one. */
export function compareDatasets(sessionId, otherId) {
  return request(`/compare/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ other_id: otherId }),
  })
}

/** The full analysis as a structured document, ready to lay out and print. */
export function getReport(sessionId) {
  return request(`/report/${encodeURIComponent(sessionId)}`)
}
