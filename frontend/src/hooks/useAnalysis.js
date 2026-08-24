import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../api'

/**
 * Runs the whole autonomous analysis for one dataset and reports its progress.
 *
 * WHY THE STAGES ARE A LIST OF REQUESTS RATHER THAN A TIMER
 * ---------------------------------------------------------
 * The product promises the AI starts working the moment a file lands, and the
 * loading screen is where that promise is either kept or exposed as theatre.
 * A timed sequence of reassuring messages is the easy version and it is
 * always caught: the messages advance at the same rate for a 200-row file and
 * a 200,000-row one, which anybody who uploads twice will notice.
 *
 * So each stage below IS a request. It is marked done when that request
 * answers, and the label describes what the server is actually doing at that
 * moment. On a small file the stages fly past; on a large one the user watches
 * the quality check sit there for four seconds, because that is genuinely what
 * is happening.
 *
 * WHY THEY RUN IN SEQUENCE RATHER THAN ALL AT ONCE. They are ordered by
 * dependency on the server -- the briefing needs the insights and the health
 * report, so firing everything in parallel would make three requests wait on
 * work a fourth was already doing. Running them in order means each arrives
 * warm, and it is what lets the indicator show one honest stage at a time
 * instead of five spinners.
 */

/**
 * The stages, in the order they run.
 *
 * `key` names the field the result lands in. `label` is written in the present
 * continuous and in the first person, because this screen is the one place the
 * app speaks as the thing doing the work.
 */
export const STAGES = [
  {
    key: 'health',
    label: 'Checking your data for problems',
    fetch: (id) => api.getHealthReport(id),
  },
  {
    key: 'insights',
    label: 'Looking for trends, patterns and anything unusual',
    fetch: (id) => api.getInsights(id),
  },
  {
    key: 'dashboard',
    label: 'Choosing the charts this data deserves',
    fetch: (id) => api.getDashboard(id),
  },
  {
    key: 'briefing',
    label: 'Writing up what I found',
    fetch: (id) => api.getBriefing(id),
  },
  {
    key: 'questions',
    label: 'Working out what you might want to ask',
    fetch: (id) => api.getQuestions(id),
  },
]

const EMPTY = {
  health: null,
  insights: null,
  dashboard: null,
  briefing: null,
  questions: null,
  recommendations: null,
}

export default function useAnalysis(sessionId, { onExpired } = {}) {
  const [data, setData] = useState(EMPTY)
  const [stageIndex, setStageIndex] = useState(0)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  // A counter rather than a boolean, so `refresh()` can invalidate a run that
  // is still in flight. Without it, a slow request from the pre-clean analysis
  // could land after the post-clean one and overwrite good data with stale
  // data -- the classic race, and here it would show the old health score
  // beside the new row count.
  const runRef = useRef(0)

  // Which session the recommendations have already been requested for. See
  // loadRecommendations for why this is a ref and not derived from state.
  const requestedRecommendations = useRef(null)

  const run = useCallback(async () => {
    if (!sessionId) return
    const run = (runRef.current += 1)

    setData(EMPTY)
    requestedRecommendations.current = null
    setStageIndex(0)
    setDone(false)
    setError('')

    for (let index = 0; index < STAGES.length; index += 1) {
      if (runRef.current !== run) return
      const stage = STAGES[index]
      setStageIndex(index)

      try {
        const result = await stage.fetch(sessionId)
        if (runRef.current !== run) return
        setData((current) => ({ ...current, [stage.key]: result }))
      } catch (caught) {
        if (runRef.current !== run) return
        if (caught.status === 404) {
          onExpired?.()
          return
        }
        // One stage failing must not cost the other four. The workspace renders
        // whatever arrived and says what is missing, which is far better than
        // an all-or-nothing screen where a single slow model call loses the
        // charts, the health report and the findings along with it.
        setError(caught.message)
      }
    }

    if (runRef.current === run) {
      setStageIndex(STAGES.length)
      setDone(true)
    }
  }, [sessionId, onExpired])

  useEffect(() => {
    // A fetch effect: this IS the synchronisation with an external system,
    // and the request has to leave in the same tick the effect runs.
    // oxlint-disable-next-line react/set-state-in-effect
    run()
  }, [run])

  /**
   * Fetch the recommendations, which are NOT part of the opening run.
   *
   * They cost a model round trip and are read by a minority of users, on a tab
   * they have to open. Putting them in the sequence above would add a second
   * or two to the wait before anyone sees anything, to prepare something most
   * people will not look at.
   */
  const loadRecommendations = useCallback(async () => {
    if (!sessionId) return
    // Guarded by a ref rather than by checking `data.recommendations`.
    //
    // The caller fires this from an effect that depends on the analysis object,
    // and that object is rebuilt on every render -- so a check against state
    // would still be false for every render between the request leaving and the
    // response landing, and the tab would issue a burst of identical requests
    // while the first one was in flight. A ref is set synchronously and so
    // closes that window entirely.
    if (requestedRecommendations.current === sessionId) return
    requestedRecommendations.current = sessionId

    try {
      const result = await api.getRecommendations(sessionId)
      setData((current) => ({ ...current, recommendations: result }))
    } catch {
      // Silent: the tab renders its own empty state, and a banner about a
      // failed background fetch on a tab the user just opened is noise. The
      // ref is cleared so pressing the tab again retries.
      requestedRecommendations.current = null
    }
  }, [sessionId])

  /** Replace one slice after something changed it — used by the cleaner. */
  const patch = useCallback((key, value) => {
    setData((current) => ({ ...current, [key]: value }))
  }, [])

  return {
    ...data,
    stageIndex,
    stage: STAGES[Math.min(stageIndex, STAGES.length - 1)],
    stages: STAGES,
    done,
    error,
    refresh: run,
    patch,
    loadRecommendations,
  }
}
