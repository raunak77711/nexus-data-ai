import NexusMark from './NexusMark'
import { Spark } from './NavBar'
import './Footer.css'

/**
 * The footer. Present on every page except the analyse workspace.
 *
 * WHY NOT IN THE WORKSPACE. The workspace is an application screen with its
 * own full-height rail and a scroll position that belongs to a dataset; a
 * marketing footer under it would be a wall the user hits at the end of their
 * own data. Home, Datasets and About are documents, and documents end.
 *
 * WHAT IS DELIBERATELY NOT HERE: social links, a newsletter, a status badge,
 * a second copy of the feature list. A footer earns its place by answering
 * "where else can I go" and "who made this", and this one does not pretend to
 * be a sitemap for a four-page product.
 */

const LINKS = [
  { id: 'home', label: 'Home' },
  { id: 'analyze', label: 'Analyze' },
  { id: 'datasets', label: 'Datasets' },
  { id: 'about', label: 'About' },
]

export default function Footer({ onRoute, onOpenAssistant }) {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <div className="footer__brand">
          <NexusMark size={30} className="footer__mark" />
          <p className="footer__name">Nexus Data AI</p>
          <p className="footer__tagline">Turn raw data into understanding.</p>
        </div>

        <nav className="footer__nav" aria-label="Footer">
          <p className="eyebrow footer__heading">Product</p>
          <ul className="footer__list">
            {LINKS.map((link) => (
              <li key={link.id}>
                <button
                  type="button"
                  className="footer__link"
                  onClick={() => onRoute(link.id)}
                >
                  {link.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="footer__nav">
          <p className="eyebrow footer__heading">Ask</p>
          <button
            type="button"
            className="footer__link footer__link--action"
            onClick={onOpenAssistant}
          >
            <Spark className="footer__spark" />
            AI Analyst
          </button>
          <p className="footer__note">
            Every figure it quotes is calculated from your rows. It writes the
            sentence, never the number.
          </p>
        </div>
      </div>

      <div className="footer__base">
        <p className="footer__copy">
          &copy; {new Date().getFullYear()} Nexus Data AI
        </p>
        <p className="footer__copy footer__copy--quiet">
          Built for curious people, not just data scientists.
        </p>
      </div>
    </footer>
  )
}
