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

/** Ask the grounded assistant a question about the current dataset. */
export function sendChat(sessionId, message, history = []) {
  return request(`/chat/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })
}
