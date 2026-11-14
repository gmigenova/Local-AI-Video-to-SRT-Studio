// In-flight state shown inside the Translate dialog while subtitles are
// being translated: pulse-ring hero, language pair, cycling status
// messages, an indeterminate meter and an elapsed clock. Resolves into a
// short success beat ("Translated N of M subtitles") before the dialog
// hands the result over to the editor.

import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Check, Languages } from 'lucide-react'

import type { TranslationEngineId } from '../../../types'
import { formatDuration } from '../../../utils/format'

interface TranslatingStateProps {
  phase: 'translating' | 'success'
  engine: TranslationEngineId
  model: string
  subtitleCount: number
  sourceLabel: string
  targetLabel: string
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

      <div className="relative flex h-16 w-16 items-center justify-center">
        {phase === 'translating' ? (
          <>
            <span className="animate-pulse-ring absolute inset-0 rounded-full border-2 border-accent/35 opacity-0" />
            <span
              className="animate-pulse-ring absolute inset-0 rounded-full border-2 border-accent/35 opacity-0"
              style={{ animationDelay: '0.8s' }}
            />
            <span
              className="animate-pulse-ring absolute inset-0 rounded-full border-2 border-accent/35 opacity-0"
              style={{ animationDelay: '1.6s' }}
            />
            <span className="relative flex h-16 w-16 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Languages size={26} />
            </span>
          </>
        ) : (
          <span className="animate-success-pop relative flex h-16 w-16 items-center justify-center rounded-full bg-success/15 text-success">
            <Check size={28} strokeWidth={2.5} />
          </span>
        )}
      </div>

      <p className="mt-5 flex items-center gap-2 text-sm font-medium">
        {sourceLabel}
        <ArrowRight
          size={14}
          aria-hidden
          className={phase === 'translating' ? 'animate-arrow-pulse text-accent' : 'text-success'}
        />
        {targetLabel}
      </p>

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
