import { useCallback, useEffect, useState } from 'react'
import NexusMark from './NexusMark'
import './NavBar.css'

/**
 * The one navigation bar, on every page.
 *
 * WHY THIS EXISTS SEPARATELY FROM THE WORKSPACE RAIL
 * --------------------------------------------------
 * They answer different questions. This bar answers "where in the product am
 * I?" — four places, always the same four, always in the same order. The rail
 * inside the analyse page answers "where in this dataset am I?", and its items
 * are meaningless without one open. Merging them would put Story, Charts and
 * Health in the global chrome, greyed out, on a page where no file exists.
 *
 * THE TWO RIGHT-HAND ACTIONS ARE NOT NAVIGATION and are styled so. "AI
 * Analyst" opens a panel over the current page and "Upload dataset" opens a
 * file picker; neither takes you anywhere, so neither gets an active state or
 * an underline. The rule the whole bar follows is that things which change the
 * page and things which do something look different.
 *
 * MOBILE. Below 860px the four links move into a disclosure under the bar and
 * "Upload dataset" stays out — it is the one action somebody arriving on a
 * phone is most likely to want, and burying the product's primary verb behind
 * a hamburger to save 120px is a bad trade.
 */

const LINKS = [
  { id: 'home', label: 'Home' },
  { id: 'analyze', label: 'Analyze' },
  { id: 'datasets', label: 'Datasets' },
  { id: 'about', label: 'About' },
]

export default function NavBar({
  route,
  onRoute,
  onUpload,
  onOpenAssistant,
  disabled,
  narrowed,
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  // Read once at initialisation rather than in the effect: a page restored
  // mid-scroll (a reload, a Back) must render the bar already separated
  // instead of flashing borderless for one frame.
  const [lifted, setLifted] = useState(() => window.scrollY > 8)

  /**
   * The bar gains a border and a stronger blur once the page has moved.
   *
   * At the very top it is borderless and sits on the hero as part of it; the
   * moment content starts passing underneath it separates itself. That is the
   * entire "premium navbar" trick and it costs one class.
   */
  useEffect(() => {
    const onScroll = () => setLifted(window.scrollY > 8)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  /** Navigating anywhere closes the mobile menu; leaving it open is a bug.
   *  Done here, at the event that causes it, rather than in an effect on
   *  `route` -- which would fire a second render after every navigation to
   *  set a boolean that was already known when the click happened. */
  const navigate = useCallback(
    (id) => {
      setMenuOpen(false)
      onRoute(id)
    },
    [onRoute],
  )

  useEffect(() => {
    if (!menuOpen) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  return (
    <header
      className={[
        'nav',
        lifted ? 'nav--lifted' : '',
        // On a wide screen the assistant is a column beside the page, not an
        // overlay, so the bar gives up its width the way the workspace does.
        // Without this the panel slides over the bar's own right-hand actions
        // and clips them mid-word.
        narrowed ? 'nav--narrowed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="nav__inner">
        {/* ------------------------------------------------------- brand -- */}
        <button
          type="button"
          className="nav__brand"
          onClick={() => navigate('home')}
          aria-label="Nexus Data AI — home"
        >
          <NexusMark size={26} className="nav__mark" />
          <span className="nav__wordmark">
            <span className="nav__word">Nexus</span>
            <span className="nav__sub">Data AI</span>
          </span>
        </button>

        {/* --------------------------------------------------------- nav -- */}
        <nav className="nav__links" aria-label="Main">
          {LINKS.map((link) => (
            <button
              key={link.id}
              type="button"
              className="nav__link"
              aria-current={route === link.id ? 'page' : undefined}
              onClick={() => navigate(link.id)}
            >
              {link.label}
            </button>
          ))}
        </nav>

        {/* ----------------------------------------------------- actions -- */}
        <div className="nav__actions">
          <button
            type="button"
            className="nav__action"
            onClick={onOpenAssistant}
          >
            <Spark className="nav__spark" />
            AI Analyst
          </button>

          <button
            type="button"
            className="nav__action nav__action--primary"
            onClick={onUpload}
            disabled={disabled}
            title={
              disabled
                ? 'The analysis service is not responding yet.'
                : 'Choose a CSV file to analyse'
            }
          >
            Upload dataset
          </button>

          <button
            type="button"
            className="nav__menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="nav-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="sr-only">{menuOpen ? 'Close menu' : 'Open menu'}</span>
            <span className={`nav__burger ${menuOpen ? 'nav__burger--open' : ''}`.trim()}>
              <i />
              <i />
            </span>
          </button>
        </div>
      </div>

      {/* The mobile disclosure. Rendered always and hidden with a height
          transition rather than unmounted, so it opens and closes with motion
          instead of appearing. */}
      <div
        className={`nav__menu ${menuOpen ? 'nav__menu--open' : ''}`.trim()}
        id="nav-menu"
        inert={!menuOpen}
      >
        <div className="nav__menu-inner">
          {LINKS.map((link) => (
            <button
              key={link.id}
              type="button"
              className="nav__menu-link"
              aria-current={route === link.id ? 'page' : undefined}
              onClick={() => navigate(link.id)}
            >
              {link.label}
            </button>
          ))}
          <button
            type="button"
            className="nav__menu-link nav__menu-link--action"
            onClick={() => {
              setMenuOpen(false)
              onOpenAssistant()
            }}
          >
            <Spark className="nav__spark" />
            AI Analyst
          </button>
        </div>
      </div>
    </header>
  )
}

/** The four-point star used wherever the product speaks as the analyst. */
export function Spark({ className = '' }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden="true" focusable="false">
      <path
        d="M8 1.4 9.35 6.65 14.6 8 9.35 9.35 8 14.6 6.65 9.35 1.4 8 6.65 6.65z"
        fill="currentColor"
      />
    </svg>
  )
}
