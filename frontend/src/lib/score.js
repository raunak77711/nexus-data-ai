/**
 * Where "good", "fair" and "poor" start.
 *
 * In its own module because two components draw the same score in two forms --
 * the ring on the Datasets cards and the Story header, the chip in the Analyze
 * header -- and two components disagreeing about where a band begins is the
 * kind of bug nobody reports and everybody notices.
 *
 * The thresholds are a presentation decision, not a duplicate of the server's:
 * core/health.py sends the GRADE as a word and this only picks which of three
 * CSS values to use. A round trip to learn which border colour to paint would
 * be a request to render a border.
 */
export function scoreBand(score) {
  if (score >= 75) return 'good'
  if (score >= 50) return 'fair'
  return 'poor'
}
