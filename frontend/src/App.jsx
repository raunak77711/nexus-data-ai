import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from './api'
import ArchetypeSelect from './components/ArchetypeSelect'
import EmptyState from './components/EmptyState'
import ForecastPanel from './components/ForecastPanel'
import ProfileTable from './components/ProfileTable'
import RoutingBanner from './components/RoutingBanner'
import StatsStrip from './components/StatsStrip'
import UploadPane from './components/UploadPane'
import WorldView from './components/WorldView'
import './App.css'

/**
 * Layout shell, session state, and every fetch the app makes.
 *
 * STATE LIVES HERE, DELIBERATELY. There is no store and no context. The whole
 * application state is one session id and the four things derived from it
 * (profile, routing, world, forecast), and every component that needs any of
 * them is at most two levels down. Introducing Redux or a context provider for
 * that would be architecture as decoration -- more files, more indirection, and
 * nothing that could not be read off this one component.
 *
 * The rule the components follow: they render props and raise events. Not one
 * of them calls fetch. That is what makes them testable in isolation and what
 * keeps every loading and error state visible in a single place -- here -- where
 * it is possible to check that none of them is missing.
 */

const DEFAULT_PARAMS = { freq: 'D', rolling_window: 7, time_filter: null }

export default function App() {
  // ---------------------------------------------------------------- session
  const [session, setSession] = useState(null)
  const [routing, setRouting] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('idle') // idle|uploading|loaded|error
  const [uploadError, setUploadError] = useState('')
  const [pendingSample, setPendingSample] = useState(null)

  // ------------------------------------------------------------------ world
  const [archetype, setArchetype] = useState(null)
  const [params, setParams] = useState(DEFAULT_PARAMS)
  const [world, setWorld] = useState(null)
  const [worldLoading, setWorldLoading] = useState(false)
  const [worldError, setWorldError] = useState('')

  // --------------------------------------------------------------- forecast
  const [forecast, setForecast] = useState(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState('')
  const [horizon, setHorizon] = useState(14)

  // ------------------------------------------------------------ environment
  const [samples, setSamples] = useState(null) // null = still loading
  const [backend, setBackend] = useState({ state: 'checking', version: '' })

  /**
   * Guards against a stale response overwriting a newer one.
   *
   * Dragging the rolling-window slider can put two world requests in flight;
   * they are not guaranteed to come back in the order they were sent, and the
   * older one arriving second would silently replace the chart the user is
   * actually waiting for. Each request takes a ticket, and only the newest
   * ticket is allowed to write state.
   */
  const worldTicket = useRef(0)

  /**
   * A 404 on any call means the server has forgotten this upload. Say so.
   *
   * Declared before the effects that call it rather than hoisted below them:
   * a function declaration would work at runtime, but reading the file top to
   * bottom should not require knowing that.
   */
  const expireSession = useCallback(() => {
    setSession(null)
    setRouting(null)
    setArchetype(null)
    setWorld(null)
    setForecast(null)
    setUploadStatus('error')
    setUploadError('That session expired on the server. Please upload the file again.')
  }, [])

  /* ------------------------------------------------------------ boot checks */
  useEffect(() => {
    let cancelled = false

    api
      .getHealth()
      .then((body) => {
        if (!cancelled) setBackend({ state: 'up', version: body.version })
      })
      .catch((error) => {
        if (!cancelled) setBackend({ state: 'down', message: error.message })
      })

    api
      .listSamples()
      .then((list) => {
        if (!cancelled) setSamples(list)
      })
      .catch(() => {
        // A failed sample listing is not worth an error banner: the upload zone
        // still works, and the empty state degrades to "no samples on the
        // server", which is the same thing the user needs to know either way.
        if (!cancelled) setSamples([])
      })

    return () => {
      cancelled = true
    }
  }, [])

  /* ------------------------------------------------------------- new upload */
  const adoptSession = useCallback(async (payload) => {
    setSession(payload)
    setUploadStatus('loaded')
    setUploadError('')
    setWorld(null)
    setForecast(null)
    setForecastError('')
    setWorldError('')
    setParams(DEFAULT_PARAMS)

    try {
      const decision = await api.getRoute(payload.session_id)
      setRouting(decision)
      setArchetype(decision.archetype)
    } catch (error) {
      // The upload itself succeeded, so the session is usable; only the banner
      // is missing. Falling back to tabular gives the user something rather
      // than a page stuck with no archetype selected.
      setRouting(null)
      setArchetype('tabular')
      setWorldError(`Routing could not be read: ${error.message}`)
    }
  }, [])

  const handleFile = useCallback(
    async (file) => {
      setUploadStatus('uploading')
      setUploadError('')
      try {
        const payload = await api.uploadCsv(file)
        // The File object is the only place the byte size is known -- the API
        // reports rows and columns, not bytes.
        await adoptSession({ ...payload, file_size: file.size })
      } catch (error) {
        setUploadStatus('error')
        setUploadError(error.message)
      }
    },
    [adoptSession],
  )

  const handleSample = useCallback(
    async (key) => {
      setPendingSample(key)
      setUploadStatus('uploading')
      setUploadError('')
      try {
        const payload = await api.loadSample(key)
        const meta = samples?.find((sample) => sample.key === key)
        await adoptSession({ ...payload, file_size: meta?.n_bytes })
      } catch (error) {
        setUploadStatus('error')
        setUploadError(error.message)
      } finally {
        setPendingSample(null)
      }
    },
    [adoptSession, samples],
  )

  /* --------------------------------------------------------- build the world */
  useEffect(() => {
    if (!session || !archetype) return undefined

    const ticket = ++worldTicket.current
    let cancelled = false

    // Setting state at the top of a fetch effect is exactly the case the
    // "no setState in an effect" guidance carves out: the effect IS the
    // synchronisation with an external system, and the loading flag has to be
    // raised in the same tick the request leaves, or there is a frame in which
    // the old world is on screen with no indication that a new one is coming.
    // oxlint-disable-next-line react/set-state-in-effect -- see above
    setWorldLoading(true)
    setWorldError('')

    api
      .buildWorld(session.session_id, archetype, params)
      .then((payload) => {
        if (cancelled || ticket !== worldTicket.current) return
        setWorld(payload)
      })
      .catch((error) => {
        if (cancelled || ticket !== worldTicket.current) return
        setWorld(null)
        setWorldError(error.message)
        if (error.status === 404) expireSession()
      })
      .finally(() => {
        if (!cancelled && ticket === worldTicket.current) setWorldLoading(false)
      })

    return () => {
      cancelled = true
    }
    // `params` is a fresh object on every change, which is exactly the intent:
    // any control change is a new world.
  }, [session, archetype, params, expireSession])

  /* ------------------------------------------------------------- forecasting */
  const runForecast = useCallback(async () => {
    if (!session) return
    setForecastLoading(true)
    setForecastError('')
    try {
      const payload = await api.runForecast(session.session_id, horizon)
      setForecast(payload)
    } catch (error) {
      setForecast(null)
      setForecastError(error.message)
      if (error.status === 404) expireSession()
    } finally {
      setForecastLoading(false)
    }
  }, [session, horizon, expireSession])

  /* ------------------------------------------------------------------ derived */

  /**
   * Day bounds for the geo time slider, read from the profile's own date stats.
   *
   * Derived rather than requested: profile_column already returns min_date and
   * max_date for every datetime column, so a dedicated endpoint would be a
   * second source for a number the client is already holding.
   */
  const timeBounds = useMemo(() => {
    const name = routing?.time_col
    if (!name || !session?.profile) return null
    const column = session.profile.columns.find((item) => item.name === name)
    if (!column?.min_date || !column?.max_date) return null

    const startMs = Date.parse(column.min_date)
    const endMs = Date.parse(column.max_date)
    if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs <= startMs) return null

    return { startMs, endMs, totalDays: Math.ceil((endMs - startMs) / 86_400_000) }
  }, [routing, session])

  const canForecast = Boolean(routing?.time_col && routing?.target_col)

  /* --------------------------------------------------------------- rendering */
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <a className="brand" href="/">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                   strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18" />
              </svg>
            </span>
            <span className="brand-text">
              AI Data <strong>Worlds</strong>
            </span>
          </a>

          <div className="app-header-right">
            {session && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setSession(null)
                  setRouting(null)
                  setArchetype(null)
                  setWorld(null)
                  setForecast(null)
                  setUploadStatus('idle')
                  setUploadError('')
                }}
              >
                New dataset
              </button>
            )}
            <span className="health" data-state={backend.state} title={backend.message ?? ''}>
              <span className="health-dot" aria-hidden="true" />
              {backend.state === 'up' && `API v${backend.version}`}
              {backend.state === 'checking' && 'Connecting…'}
              {backend.state === 'down' && 'API offline'}
            </span>
          </div>
        </div>
      </header>

      <main className="app-main">
        {backend.state === 'down' && (
          <p className="status-note app-offline" data-tone="error">
            <strong>The API is not responding.</strong> {backend.message} Start it
            with <code>uvicorn backend.main:app --reload</code> and reload this page.
          </p>
        )}

        {!session ? (
          <>
            <EmptyState
              samples={samples}
              onLoadSample={handleSample}
              loadingKey={pendingSample}
              disabled={uploadStatus === 'uploading' || backend.state === 'down'}
            />
            <div className="empty-upload">
              <UploadSection
                onFile={handleFile}
                status={uploadStatus}
                error={uploadError}
                disabled={backend.state === 'down'}
              />
            </div>
          </>
        ) : (
          <div className="workspace">
            <div className="workspace-top">
              <StatsStrip profile={session.profile} filename={session.filename} />
            </div>

            <div className="workspace-body">
              <div className="workspace-main">
                <RoutingBanner routing={routing} />

                <ArchetypeSelect
                  value={archetype}
                  routed={routing?.archetype}
                  onChange={setArchetype}
                  disabled={worldLoading}
                />

                <WorldView
                  /* Keyed on the session so a new dataset gets fresh controls
                     rather than inheriting the previous file's slider values. */
                  key={session.session_id}
                  archetype={archetype}
                  world={world}
                  params={params}
                  onParamsChange={setParams}
                  loading={worldLoading}
                  error={worldError}
                  timeBounds={timeBounds}
                />

                {canForecast && (
                  <ForecastPanel
                    forecast={forecast}
                    loading={forecastLoading}
                    error={forecastError}
                    onRun={runForecast}
                    horizon={horizon}
                    onHorizonChange={setHorizon}
                  />
                )}
              </div>

              <aside className="workspace-side" aria-label="Dataset details">
                <section className="panel side-panel" aria-labelledby="profile-heading">
                  <div className="section-title">
                    <h2 id="profile-heading">Columns</h2>
                    <span className="section-note tnum">{session.profile.n_cols}</span>
                  </div>
                  <ProfileTable profile={session.profile} />
                </section>

                <section className="panel side-panel" aria-labelledby="replace-heading">
                  <h2 id="replace-heading" className="side-panel-heading">
                    Swap the dataset
                  </h2>
                  <UploadSection
                    onFile={handleFile}
                    status={uploadStatus === 'loaded' ? 'idle' : uploadStatus}
                    error={uploadError}
                    disabled={backend.state === 'down'}
                    compact
                  />
                </section>
              </aside>
            </div>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p>
          Every figure ships with the code that produced it — not a description of
          it, the source that ran.
        </p>
      </footer>
    </>
  )
}

/**
 * Thin wrapper so the upload zone can appear both on the empty state and in the
 * sidebar without either call site repeating the prop list.
 */
function UploadSection({ onFile, status, error, disabled, compact, filename, fileSize }) {
  return (
    <div className={compact ? 'upload-compact' : undefined}>
      <UploadPane
        onFile={onFile}
        status={status}
        error={error}
        disabled={disabled}
        filename={filename ?? null}
        fileSize={fileSize ?? null}
      />
    </div>
  )
}
