import useReveal from '../hooks/useReveal'
import NexusMark from './NexusMark'
import './About.css'

/**
 * About: what Nexus believes, and what it actually does about it.
 *
 * WHY AN ABOUT PAGE IN A TOOL
 * ---------------------------
 * Because the product makes a claim that has to be defended somewhere. "AI
 * that explains your data" is, on the face of it, exactly the claim of every
 * tool that hallucinates a number into a sentence and ships it. The reason to
 * trust this one is a design decision -- the model never writes a figure --
 * and a design decision needs a page that says it out loud.
 *
 * So this is not a company page. There is no team, no funding, no mission
 * statement. It is the argument for the product, in the order somebody
 * sceptical would want it: the problem, the position, the mechanism, the
 * guarantee, and who it is for.
 */

const PROCESS = [
  {
    n: '01',
    label: 'Upload',
    detail:
      'A CSV goes in. No schema to declare, no columns to map, no account to make.',
  },
  {
    n: '02',
    label: 'Understand',
    detail:
      'Every column is profiled — what type it really is, how complete, how varied, what it ranges over.',
  },
  {
    n: '03',
    label: 'Discover',
    detail:
      'Trends, relationships, concentrations and outliers are computed, then ranked against each other rather than within their own kind.',
  },
  {
    n: '04',
    label: 'Ask',
    detail:
      'Anything else you want to know, in a sentence. The question becomes a calculation, and the calculation becomes an answer you can check.',
  },
  {
    n: '05',
    label: 'Act',
    detail:
      'Fix the data problems it found, export the write-up, or compare this file against the one from last month.',
  },
]

export default function About({ onRoute, onOpenAssistant }) {
  const [processRef, processShown] = useReveal()
  const [principleRef, principleShown] = useReveal()

  return (
    <div className="about">
      {/* ----------------------------------------------------------- hero -- */}
      <section className="about__hero">
        <div className="about__inner about__inner--narrow">
          <p className="eyebrow">About Nexus</p>
          <h1 className="about__headline">
            Data is complicated.
            <br />
            Understanding it shouldn&rsquo;t be.
          </h1>
          <p className="about__lede">
            Nexus Data AI turns a raw dataset into something you can actually
            use: insights written in sentences, the visualizations that back
            them up, and a conversation you can have with your own numbers.
          </p>
        </div>
      </section>

      {/* ------------------------------------------------------ why nexus -- */}
      <section className="about__band">
        <div className="about__inner about__split">
          <p className="eyebrow about__band-label">Why Nexus</p>
          <div className="about__band-body">
            <p className="about__statement">
              Most data tools make people learn the tool.
              <br />
              <em>Nexus makes the tool understand the data.</em>
            </p>
            <p className="about__prose">
              The usual bargain in this category is that you get power in
              exchange for fluency: pivot tables, query languages, chart
              builders, a dashboard you have to design before it can tell you
              anything. All of it assumes you already know what you are looking
              for. Most people opening a spreadsheet do not — that is the
              reason they opened it.
            </p>
            <p className="about__prose">
              So Nexus inverts the work. The file arrives, and the analysis has
              already been done by the time you have finished reading the first
              sentence about it. What is in here, what is changing, what is
              unusual, what cannot be trusted — answered before you have asked.
            </p>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- how it works -- */}
      <section
        className="about__band"
        ref={processRef}
        data-shown={processShown || undefined}
      >
        <div className="about__inner">
          <header className="about__band-head">
            <p className="eyebrow">How it works</p>
            <h2 className="about__band-title">Five steps, in order.</h2>
          </header>

          {/* A timeline rather than a grid, because these genuinely happen one
              after another and four of the five are automatic. The rule down
              the left is what says "sequence"; laying them out as tiles would
              claim they are five options. */}
          <ol className="process">
            {PROCESS.map((step, index) => (
              <li key={step.n} className="process__step" style={{ '--i': index }}>
                <span className="process__marker" aria-hidden="true" />
                <span className="process__n">{step.n}</span>
                <h3 className="process__label">{step.label}</h3>
                <p className="process__detail">{step.detail}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ------------------------------------------------------- guarantee -- */}
      <section
        className="about__band about__band--quote"
        ref={principleRef}
        data-shown={principleShown || undefined}
      >
        <div className="about__inner about__inner--narrow">
          <NexusMark size={34} className="about__mark" />
          <p className="eyebrow">The guarantee</p>
          <h2 className="about__principle">
            The AI writes the sentence.
            <br />
            It never writes the number.
          </h2>
          <p className="about__prose">
            Every figure Nexus shows you was computed from your rows by code you
            could run yourself. The model&rsquo;s job is to phrase what the
            calculation found, decide what matters most and answer follow-up
            questions — and its wording is checked against the computed values
            before it reaches you. A sentence that introduces a number nobody
            calculated is thrown away rather than shown.
          </p>
          <p className="about__prose">
            That is why nearly everything in this interface carries a small mark
            saying how it was produced. A tool that tells you things you cannot
            verify is asking to be trusted; one that shows its working is
            earning it.
          </p>
        </div>
      </section>

      {/* ------------------------------------------------------------- for -- */}
      <section className="about__band about__band--close">
        <div className="about__inner about__inner--narrow">
          <h2 className="about__closing">
            Built for curious people, not just data scientists.
          </h2>
          <p className="about__lede">
            If you have a spreadsheet and a question, that is the entire list of
            prerequisites.
          </p>

          <div className="about__actions">
            <button
              type="button"
              className="btn btn-primary about__cta"
              onClick={() => onRoute('home')}
            >
              Upload a dataset
            </button>
            <button
              type="button"
              className="btn btn-secondary about__cta"
              onClick={onOpenAssistant}
            >
              Ask the analyst
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
