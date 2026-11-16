// Tweened numeric display: e.g. the Processing % readout, which otherwise
// jumps 15–20 points with every 1.5s poll. Duration stays under the poll
// interval so the number still feels live.

import { useEffect, useRef, useState } from 'react'

import { usePrefersReducedMotion } from './usePrefersReducedMotion'

const easeOutCubic = (t: number) => 1 - (1 - t) ** 3

/** Tweens toward `target`. Snaps instantly on mount, when durationMs <= 0,
 *  when the user prefers reduced motion, and when the target moves
 *  backwards (progress reset — retry / new job). Consecutive retargets
 *  chain from the current tweened value, so polls blend into one glide. */
export function useTweenedNumber(target: number, durationMs = 900): number {
  const reducedMotion = usePrefersReducedMotion()
  const [display, setDisplay] = useState(target)
  const displayRef = useRef(target)
  const frameRef = useRef<number | null>(null)

  useEffect(() => {
    const from = displayRef.current
    if (reducedMotion || durationMs <= 0 || target === from || target < from) {
      displayRef.current = target
      setDisplay(target)
      return
    }

    const start = performance.now()
    let lastRounded = Math.round(from)

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs)
      if (t >= 1) {
        // land exactly on the target (the rounded-value guard below could
        // otherwise leave the final frame's 99.997… in place)
        frameRef.current = null
        displayRef.current = target
        setDisplay(target)
        return
      }
      const value = from + (target - from) * easeOutCubic(t)
      displayRef.current = value
      // only re-render when the rounded readout actually changes
      const rounded = Math.round(value)
      if (rounded !== lastRounded) {
        lastRounded = rounded
        setDisplay(value)
      }
      frameRef.current = requestAnimationFrame(step)
    }

    frameRef.current = requestAnimationFrame(step)
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [target, durationMs, reducedMotion])

  return display
}
