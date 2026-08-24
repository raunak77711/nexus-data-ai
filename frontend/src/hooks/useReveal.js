import { useEffect, useRef, useState } from 'react'

/**
 * "Has this element been scrolled into view yet?"
 *
 * Returns a ref to attach and a boolean that flips to true the first time the
 * element enters the viewport, and never flips back.
 *
 * WHY IT NEVER FLIPS BACK. An element that fades out again on the way up turns
 * scrolling into a light show and, worse, makes the page feel unstable — the
 * reader scrolls back to re-read a sentence and watches it leave. Revealing
 * once is the whole effect; repeating it is the mistake.
 *
 * WHY IntersectionObserver AND NOT A SCROLL LISTENER. A scroll handler runs on
 * the main thread on every frame of every scroll for every element using it.
 * The observer is called only when something actually crosses the threshold,
 * and it is called off the critical path.
 *
 * `rootMargin` pulls the trigger line up from the bottom of the viewport, so a
 * section has begun its entrance by the time it is properly on screen rather
 * than animating in front of a reader already looking at it.
 */
export default function useReveal({ threshold = 0.12, rootMargin = '0px 0px -12% 0px' } = {}) {
  const ref = useRef(null)
  // Starts true where there is no observer to ask -- very old browsers, some
  // test environments. Failing open is the only acceptable failure mode for a
  // mechanism that decides whether text is on screen, and deciding it at
  // initialisation keeps it out of the effect below.
  const [shown, setShown] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    const node = ref.current
    if (!node || shown) return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true)
          observer.disconnect()
        }
      },
      { threshold, rootMargin },
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [shown, threshold, rootMargin])

  return [ref, shown]
}
