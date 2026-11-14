// In-flight state shown inside the Translate dialog while subtitles are
// being translated: script glyphs from several languages orbit the
// Languages icon on a pseudo-3D ellipse — passing behind it (smaller,
// dimmer) and in front — while status messages cycle and the meter
// sweeps. Resolves into a short success beat before the dialog hands the
// result over to the editor.

import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { ArrowRight, Check, Languages } from 'lucide-react'

import type { TranslationEngineId } from '../../../types'
import { formatDuration } from '../../../utils/format'

/** One glyph per language family the app commonly deals with. */
const ORBIT_GLYPHS = ['ก', 'A', '文', 'あ', '한', 'Ω']
/** Must match the duration in the .orbit-glyph rule (index.css). */
const ORBIT_PERIOD_S = 14

interface TranslatingStateProps {
  phase: 'translating' | 'success'
  engine: TranslationEngineId
  model: string
  subtitleCount: number
  sourceLabel: string
  targetLabel: string
  /** Result of the finished request (drives the success beat). */
  result: { translated: number; total: number } | null
}

export default function TranslatingState({
  phase,
  engine,
  model,
  subtitleCount,
  sourceLabel,
  targetLabel,
  result,
}: TranslatingStateProps) {
  const reducedMotion = usePrefersReducedMotion()
  const [startedAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  const [messageIndex, setMessageIndex] = useState(0)

  const messages = useMemo(
    () => buildMessages(engine, model, subtitleCount),
    [engine, model, subtitleCount],
  )

  // elapsed clock (1s like the processing page); frozen on success
  useEffect(() => {
    if (phase === 'success') return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [phase])

  // cycling status messages — clamped, so a long Ollama run settles on
  // "Finishing up…" instead of jumping back to "Sending…"
  useEffect(() => {
    if (phase === 'success' || reducedMotion) return
    const timer = setInterval(
      () => setMessageIndex((i) => Math.min(i + 1, messages.length - 1)),
      2800,
    )
    return () => clearInterval(timer)
  }, [phase, reducedMotion, messages])

  const succeeded = phase === 'success' && result !== null

  return (
    <div
      role="status"
      aria-live="polite"
      className="animate-fade-in flex flex-col items-center px-2 py-6 text-center sm:py-8"
    >
      {/* announced content changes exactly twice: start + success */}
      <p className="sr-only">
        {succeeded
          ? `Translated ${result.translated} of ${result.total} subtitles.`
          : `Translating ${subtitleCount} subtitles from ${sourceLabel} to ${targetLabel}…`}
      </p>

      {/* hero: orbiting script glyphs around the Languages icon */}
      <div className="relative flex h-16 w-16 items-center justify-center">
        {phase === 'translating' ? (
          <>
            {ORBIT_GLYPHS.map((glyph, i) => (
              <span
                key={glyph}
                aria-hidden
                className="orbit-glyph text-sm font-semibold text-accent"
                style={
                  {
                    '--angle': `${i * (360 / ORBIT_GLYPHS.length)}deg`,
                    '--phase': `${(-i * ORBIT_PERIOD_S) / ORBIT_GLYPHS.length}s`,
                  } as CSSProperties
                }
              >
                {glyph}
              </span>
            ))}
            <span className="relative z-[2] flex h-16 w-16 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Languages size={26} />
            </span>
          </>
        ) : (
          <span className="animate-success-pop relative z-[2] flex h-16 w-16 items-center justify-center rounded-full bg-success/15 text-success">
            <Check size={28} strokeWidth={2.5} />
          </span>
        )}
      </div>

      <p className="mt-5 flex items-center gap-2 text-sm font-medium">
        {sourceLabel}
        <ArrowRight
          size={14}
          aria-hidden
          className={
            phase === 'translating' ? 'animate-arrow-pulse text-accent' : 'text-success'
          }
        />
        {targetLabel}
      </p>

      {/* cycling status / success copy — hidden from screen readers */}
      <p
        aria-hidden
        className="mt-1.5 flex min-h-6 items-center justify-center text-sm text-muted"
      >
        {succeeded ? (
          <span key="done" className="animate-msg-in">
            Translated {result.translated} of {result.total} subtitles
          </span>
        ) : (
          <span key={messageIndex} className="animate-msg-in">
            {messages[messageIndex]}
          </span>
        )}
      </p>

      <div className="mt-5 h-1.5 w-full max-w-64 overflow-hidden rounded-full bg-surface-2">
        {succeeded ? (
          <div key="done" className="animate-fade-in h-full w-full rounded-full bg-success" />
        ) : (
          <div className="animate-indeterminate h-full w-2/5 rounded-full bg-accent" />
        )}
      </div>

      <p className="mt-2.5 font-mono text-xs tabular-nums text-muted/80">
        {formatDuration(now - startedAt)}
      </p>
    </div>
  )
}

function buildMessages(engine: TranslationEngineId, model: string, count: number): string[] {
  const noun = `subtitle${count === 1 ? '' : 's'}`
  return engine === 'ollama'
    ? [
        `Sending ${count} ${noun} to Ollama…`,
        `Translating with ${model}…`,
        'Aligning translated subtitles…',
        'Finishing up…',
      ]
    : [
        `Sending ${count} ${noun} to Google Translate…`,
        'Translating text…',
        'Aligning translated subtitles…',
        'Finishing up…',
      ]
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  return reduced
}
