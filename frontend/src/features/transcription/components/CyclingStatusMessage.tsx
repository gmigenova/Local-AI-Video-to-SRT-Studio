// Rotating friendly status lines under the Processing progress bar.
// Follows TranslatingState: the visible cycling text is aria-hidden; a
// stable sr-only line carries the announcement so screen readers hear
// stage changes, not a new sentence every 2.4s.

import { useEffect, useState } from 'react'

import { usePrefersReducedMotion } from '../../../hooks/usePrefersReducedMotion'

/** Generic pool — the real stage is shown next to the progress bar and in
 *  the Stage stat; these lines set tone. Loops rather than clamps: a long
 *  transcription shouldn't sit on the last line for minutes. */
const DEFAULT_MESSAGES = [
  'Listening to the audio…',
  'Identifying speech segments…',
  'Transcribing dialogue…',
  'Matching text to timestamps…',
  'Polishing subtitle cues…',
]

const INTERVAL_MS = 2_400

interface CyclingStatusMessageProps {
  /** Stable text for assistive tech (announced only when it changes). */
  srText: string
  messages?: string[]
}

export function CyclingStatusMessage({
  srText,
  messages = DEFAULT_MESSAGES,
}: CyclingStatusMessageProps) {
  const reducedMotion = usePrefersReducedMotion()
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (reducedMotion) return
    const timer = setInterval(
      () => setIndex((i) => (i + 1) % messages.length),
      INTERVAL_MS,
    )
    return () => clearInterval(timer)
  }, [reducedMotion, messages])

  return (
    <div role="status" aria-live="polite" className="min-h-4">
      <p className="sr-only">{srText}</p>
      <p aria-hidden className="text-xs text-muted">
        <span key={index} className="animate-msg-in inline-block">
          {messages[index]}
        </span>
      </p>
    </div>
  )
}
