import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import useAnalysis from './hooks/useAnalysis'
import useRoute from './hooks/useRoute'
import About from './components/About'
import AnalystLauncher from './components/AnalystLauncher'
import Analyzing from './components/Analyzing'
import Assistant from './components/Assistant'
import DatasetsPage from './components/DatasetsPage'
import Footer from './components/Footer'
import Home from './components/Home'
import NavBar from './components/NavBar'
import NoDataset from './components/NoDataset'
import Workspace from './components/Workspace'
import './App.css'

/**
 * The whole application: four pages, one panel over all of them.
 *
 *      Home  ·  Analyze  ·  Datasets  ·  About
 *                  |
 *      (analysing) -> (workspace: story, charts, health, actions, rows, report)
 *
 * WHAT THIS FILE OWNS AND WHAT IT DOES NOT
 * ----------------------------------------
 * It owns the session, the route, and the two pieces of cross-cutting state
 * that genuinely belong to the whole app: whether the assistant is open, and
 * which detail mode the user is in. Everything else lives where it is used.
 *
 * The analysis itself is not here — `useAnalysis` runs it and owns its stages,
 * its cache and its race protection. The route is not here either —
 * `useRoute` keeps it in the URL so the browser's Back button works. That
 * separation is what keeps this file readable: this decides WHICH page, those
 * decide what is on one.
 *
 * ANALYZE IS A PAGE WITH THREE STATES, NOT THREE PAGES. Empty, working and
 * ready are the same destination at different moments — which is why an
 * upload does not navigate anywhere once you are on it, and why the loading
 * screen is not a route somebody can land on by pressing Back.
 *
 * DETAIL MODE IS PERSISTED, THE OPEN TAB IS NOT. A person who chose Advanced
 * chose it about themselves and expects it to survive a reload; a person who
 * was last on the Health tab was there about one dataset and expects to land
 * on the Story when they come back. The distinction is what state belongs to
 * the user versus what belongs to the visit.
 */

const MODE_KEY = 'nexus:mode'

function readMode() {
  try {
    const stored = window.localStorage.getItem(MODE_KEY)
    return stored === 'advanced' ? 'advanced' : 'beginner'
  } catch {
    // Private browsing, or site data blocked. A preference is not worth an
    // error path; the default is a perfectly good answer.
    return 'beginner'
  }
}

export default function App() {
  const [route, go] = useRoute()

  const [session, setSession] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('idle') // idle|uploading|error
  const [uploadError, setUploadError] = useState('')
  const [pendingSample, setPendingSample] = useState(null)
  const [pendingName, setPendingName] = useState('')

  const [tab, setTab] = useState('story')
  const [mode, setMode] = useState(readMode)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState(null)

  const [samples, setSamples] = useState(null)
  const [recentDatasets, setRecentDatasets] = useState([])
  const [backend, setBackend] = useState({ state: 'checking', version: '' })

  // The file input behind the navbar's "Upload dataset". It lives here rather
  // than in NavBar because the same control is triggered from three places —
  // the navbar, the empty analyse screen and the empty library — and three
  // hidden inputs would be three things to keep in step.
  const fileInputRef = useRef(null)

  useEffect(() => {
    try {
      window.localStorage.setItem(MODE_KEY, mode)
    } catch {
      /* see readMode */
    }
  }, [mode])

  /** A 404 on any call means the server has forgotten this dataset. Say so. */
  const expireSession = useCallback(() => {
    setSession(null)
    setUploadStatus('error')
    setUploadError(
      'That dataset is no longer on the server. Add the file again, or open ' +
        'one of your stored datasets.',
    )
  }, [])

  const analysis = useAnalysis(session?.session_id, { onExpired: expireSession })

  /* ------------------------------------------------------------ boot ----- */
  /**
   * Health is watched until it answers rather than probed once and believed.
   *
   * Asking exactly once at mount produced the worst kind of wrong banner: open
   * the page while the server is still booting — the normal order when both are
   * started together — and the app announced nothing was responding for the
   * rest of the session, telling the user to start a server that was by then
   * already running. Nothing cleared it because nothing asked again.
   */
  useEffect(() => {
    let cancelled = false
    let timer = 0
    let attempt = 0
    let loaded = false

    const loadExtras = () => {
      api
        .listSamples()
        .then((list) => !cancelled && setSamples(list))
        .catch(() => !cancelled && setSamples([]))
      api
        .listDatasets()
        .then((list) => !cancelled && setRecentDatasets(list.slice(0, 4)))
        .catch(() => {})
    }

    const probe = () => {
      if (cancelled) return
      api
        .getHealth()
        .then((body) => {
          if (cancelled) return
          attempt = 0
          setBackend({ state: 'up', version: body.version })
          if (!loaded) {
            loaded = true
            loadExtras()
          }
        })
        .catch((error) => {
          if (cancelled) return
          setBackend({ state: 'down', message: error.message })
          // 1s, 2s, 4s, 8s, then every 15s for as long as the tab is open.
          timer = window.setTimeout(probe, Math.min(1000 * 2 ** attempt, 15000))
          attempt += 1
        })
    }

    // A tab left open across a restart, or a laptop waking, should recover on
    // the user's next glance rather than waiting out the backoff.
    const recheck = () => {
      if (cancelled) return
      window.clearTimeout(timer)
      attempt = 0
      probe()
    }

    probe()
    window.addEventListener('online', recheck)
    window.addEventListener('focus', recheck)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
      window.removeEventListener('online', recheck)
      window.removeEventListener('focus', recheck)
    }
  }, [])

  /* ---------------------------------------------------------- uploading -- */
  const adopt = useCallback(
    (payload) => {
      setSession(payload)
      setUploadStatus('idle')
      setUploadError('')
      setTab('story')
      go('analyze')
    },
    [go],
  )

  const handleFile = useCallback(
    async (file) => {
      setUploadStatus('uploading')
      setUploadError('')
      setPendingName(file.name)
      // Straight to the workspace, so the honest stage-by-stage progress is
      // what the user watches rather than a home page that has gone quiet.
      go('analyze')
      try {
        adopt(await api.uploadCsv(file))
      } catch (error) {
        setUploadStatus('error')
        setUploadError(error.message)
      }
    },
    [adopt, go],
  )

  const handleSample = useCallback(
    async (key) => {
      const meta = samples?.find((sample) => sample.key === key)
      setPendingSample(key)
      setPendingName(meta?.filename ?? '')
      setUploadStatus('uploading')
      setUploadError('')
      go('analyze')
      try {
        adopt(await api.loadSample(key))
      } catch (error) {
        setUploadStatus('error')
        setUploadError(error.message)
      } finally {
        setPendingSample(null)
      }
    },
    [adopt, go, samples],
  )

  /** The navbar's Upload button, and every other "upload" affordance. */
  const pickFile = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const onFileInputChange = useCallback(
    (event) => {
      const file = event.target.files?.[0]
      // Cleared so choosing the SAME file twice in a row still fires a change
      // event. Without this, an upload that failed cannot be retried from the
      // picker at all.
      event.target.value = ''
      if (file) handleFile(file)
    },
    [handleFile],
  )

  /**
   * Open a stored dataset.
   *
   * The whole record from the datasets list is passed in rather than just an
   * id, because the list already holds the filename and the shape and /route
   * does not return either — fetching the id alone would land the user in a
   * workspace labelled "dataset.csv, 0 rows" until the analysis caught up.
   *
   * Nothing else is needed: setting the session is enough for `useAnalysis` to
   * run, and the server re-reads the file from disk if it has been evicted.
   */
  const openDataset = useCallback(
    (dataset) => {
      setSession({
        session_id: dataset.id,
        filename: dataset.filename,
        n_rows: dataset.n_rows,
        n_cols: dataset.n_cols,
        is_cleaned: dataset.is_cleaned,
      })
      setTab('story')
      setUploadStatus('idle')
      setUploadError('')
      go('analyze')
    },
    [go],
  )

  const startOver = useCallback(() => {
    setSession(null)
    setUploadStatus('idle')
    setUploadError('')
    setTab('story')
    go('home')
    // Re-read the list on the way out, so the file just analysed is on the
    // home page when it arrives rather than one visit behind.
    api
      .listDatasets()
      .then((list) => setRecentDatasets(list.slice(0, 4)))
      .catch(() => {})
  }, [go])

  /* ----------------------------------------------------------- asking ---- */
  /** Send a question to the assistant from anywhere, opening it if closed. */
  const ask = useCallback((question) => {
    setAssistantOpen(true)
    setPendingQuestion(question)
  }, [])

  const openAssistant = useCallback(() => setAssistantOpen(true), [])

  /* ---------------------------------------------------------- cleaning --- */
  /**
   * After a clean the frame has changed, so every cached analysis is about a
   * dataset that no longer exists. The health report comes back in the response
   * and is patched straight in — the user is looking at the score and it must
   * move now — and the rest is recomputed.
   */
  const handleCleaned = useCallback(
    (result) => {
      setSession((current) =>
        current ? { ...current, is_cleaned: true, n_rows: result.rows_after } : current,
      )
      analysis.patch('health', result.health)
      analysis.refresh()
    },
    [analysis],
  )

  const handleReverted = useCallback(
    (result) => {
      setSession((current) =>
        current ? { ...current, is_cleaned: false, n_rows: result.rows_after } : current,
      )
      analysis.patch('health', result.health)
      analysis.refresh()
    },
    [analysis],
  )

  /* --------------------------------------------------------- rendering --- */

  const offline = backend.state === 'down'
  const preparing = uploadStatus === 'uploading' || (Boolean(session) && !analysis.done)
  const inWorkspace = Boolean(session) && analysis.done

  // The workspace is a full-height application screen with its own rail; a
  // marketing footer under it would be a wall the reader hits at the end of
  // their own data. The three document pages get one.
  const showFooter = route !== 'analyze' || (!preparing && !inWorkspace)

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      {/* The one real file input in the app. Visually hidden rather than
          `display: none`, because a hidden-by-display input cannot be opened
          programmatically in every browser. */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        className="app-file-input"
        tabIndex={-1}
        aria-hidden="true"
        onChange={onFileInputChange}
      />

      <NavBar
        route={route}
        onRoute={go}
        onUpload={pickFile}
        onOpenAssistant={openAssistant}
        disabled={offline}
        narrowed={assistantOpen}
      />

      <main
        className={`app-shell ${route === 'analyze' && inWorkspace ? 'app-shell--app' : ''}`.trim()}
        id="main"
      >
        {/* The human sentence first, the command second and smaller.
            A banner that opens with a uvicorn invocation is addressed to
            whoever deployed this rather than to whoever is reading it — and
            the reader is the one who needs to know that nothing they do right
            now will work, and that they do not have to reload to find out
            when it does. */}
        {offline && (
          <div className="offline-banner">
            <p className="status-note" data-tone="error">
              <span>
                <strong>Not connected.</strong> Nexus cannot reach the service
                that reads your files, so uploading is paused. Nothing has been
                lost, and this page reconnects on its own.
                <span className="offline-banner__how">
                  Running it yourself? Start the backend with{' '}
                  <code>uvicorn backend.main:app --reload</code> or{' '}
                  <code>docker compose up</code>.
                </span>
              </span>
            </p>
          </div>
        )}

        {route === 'home' && (
          <Home
            onFile={handleFile}
            samples={samples}
            onLoadSample={handleSample}
            loadingKey={pendingSample}
            uploadStatus={uploadStatus}
            uploadError={uploadError}
            disabled={offline}
            onOpenAssistant={openAssistant}
            recent={recentDatasets}
            onOpenDataset={openDataset}
          />
        )}

        {route === 'analyze' && preparing && (
          <Analyzing
            filename={session?.filename ?? pendingName}
            stages={analysis.stages}
            stageIndex={session ? analysis.stageIndex : 0}
            error={analysis.error}
          />
        )}

        {route === 'analyze' && !preparing && !inWorkspace && (
          <NoDataset
            onUpload={pickFile}
            onRoute={go}
            hasDatasets={recentDatasets.length > 0}
            disabled={offline}
            error={uploadError}
          />
        )}

        {route === 'analyze' && inWorkspace && (
          <Workspace
            session={session}
            analysis={analysis}
            tab={tab}
            onTab={setTab}
            mode={mode}
            onMode={setMode}
            onAsk={ask}
            assistantOpen={assistantOpen}
            onStartOver={startOver}
            onOpenDataset={openDataset}
            onCleaned={handleCleaned}
            onReverted={handleReverted}
          />
        )}

        {route === 'datasets' && (
          <DatasetsPage
            onOpen={openDataset}
            onUpload={pickFile}
            currentId={session?.session_id ?? null}
            disabled={offline}
          />
        )}

        {route === 'about' && <About onRoute={go} onOpenAssistant={openAssistant} />}
      </main>

      {showFooter && <Footer onRoute={go} onOpenAssistant={openAssistant} />}

      <AnalystLauncher
        open={assistantOpen}
        onOpen={openAssistant}
        filename={session?.filename ?? ''}
      />

      {/* Outside <main>, and mounted on every page including the home screen.
          `sessionId` only changes which assistant answers on the server — it
          is never a reason to hide the panel, since the moment before an
          upload is the moment somebody is most likely to need one. */}
      <Assistant
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
        sessionId={session?.session_id ?? null}
        filename={session?.filename ?? ''}
        suggestions={analysis.questions?.questions ?? []}
        pendingQuestion={pendingQuestion}
        onPendingConsumed={() => setPendingQuestion(null)}
      />
    </>
  )
}
