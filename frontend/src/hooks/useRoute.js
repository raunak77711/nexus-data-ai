import { useCallback, useEffect, useState } from 'react'

/**
 * The router. Four destinations, kept in the URL hash.
 *
 * WHY A HASH AND NOT A LIBRARY
 * ----------------------------
 * This app has four pages and no nested routes, no route params and no data
 * loading tied to a path. React Router would add a dependency, a provider, and
 * a build-time cost to solve a problem that is genuinely this small.
 *
 * WHY THE URL AT ALL, given the app could hold the page in state: because
 * without it the browser Back button leaves the site. Somebody who opens
 * About from the home page and presses Back expects the home page, and a
 * state-only "router" gives them whatever was open before Nexus. Writing the
 * hash makes Back, Forward, reload and a pasted link all behave.
 *
 * Unknown hashes fall back to home rather than rendering a 404 screen. There
 * is no scenario in a four-page app where a typo'd hash deserves its own page.
 */

export const ROUTES = ['home', 'analyze', 'datasets', 'about']

function fromHash() {
  const raw = window.location.hash.replace(/^#\/?/, '').split(/[?#]/)[0]
  return ROUTES.includes(raw) ? raw : 'home'
}

export default function useRoute() {
  const [route, setRoute] = useState(fromHash)

  useEffect(() => {
    const onHashChange = () => setRoute(fromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const go = useCallback((next) => {
    const target = ROUTES.includes(next) ? next : 'home'
    const hash = target === 'home' ? '#/' : `#/${target}`

    // Setting the hash fires `hashchange`, which is what actually moves the
    // page. When it is already the current hash no event fires, so the state
    // is set directly — otherwise clicking the link for the page you are on
    // would do nothing at all, including not scrolling back to the top.
    if (window.location.hash !== hash) {
      window.location.hash = hash
    } else {
      setRoute(target)
    }

    // A new page starts at its top. Instant rather than smooth: a smooth
    // scroll across a full page of content on every navigation is the kind of
    // motion that reads as showing off rather than as helping.
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [])

  return [route, go]
}
