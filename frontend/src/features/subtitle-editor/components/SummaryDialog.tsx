// Video summary dialog: a local Ollama model reads the saved subtitles and
// produces a short summary plus timestamped key points. The result is
// persisted server-side (summary.json), so it survives reloads; clicking a
// key point seeks the video to its cue.

import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  Copy,
  Info,
  ListTree,
  Play,
  Sparkles,
} from 'lucide-react'

import { useSummarize, useSummary, useTranslationInfo } from '../../../api/hooks'
import type { SummaryResult } from '../../../types'
import { Button, Field, Modal, Spinner, inputClass } from '../../../components/ui'
import { formatDuration } from '../../../utils/format'

/** Preferred summary default when several models are installed. */
const PREFERRED_MODEL_HINT = 'qwen'

interface SummaryDialogProps {
  jobId: string
  /** Flush pending editor edits so the summary covers the latest text. */
  onBeforeSummarize: () => Promise<boolean>
  /** Job's detected language code — picks the output-language default. */
  detectedLanguage: string | null | undefined
  /** Seek the video to a key point's cue (ms). */
  onSeek: (ms: number) => void
  onClose: () => void
}

export default function SummaryDialog({
  jobId,
  onBeforeSummarize,
  detectedLanguage,
  onSeek,
  onClose,
}: SummaryDialogProps) {
  const info = useTranslationInfo()
  const summaryQuery = useSummary(jobId)
  const summarize = useSummarize()

  const ollama = info.data?.engines?.ollama
  const ollamaAvailable = ollama?.available ?? false
  const installed = useMemo(() => ollama?.models ?? [], [ollama])

  const [model, setModel] = useState<string>(
    installed.find((name) => name.includes(PREFERRED_MODEL_HINT)) ??
      installed[0] ??
      'qwen2.5:7b',
  )
  const [language, setLanguage] = useState<'th' | 'en'>(
    (detectedLanguage ?? '').startsWith('th') ? 'th' : 'en',
  )
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const busy = summarize.isPending

  // default model arrives with the engine status (after first render)
  useEffect(() => {
    if (ollamaAvailable && installed.length > 0) {
      setModel((m) =>
        installed.includes(m)
          ? m
          : (installed.find((name) => name.includes(PREFERRED_MODEL_HINT)) ??
            installed[0] ??
            m),
      )
    }
  }, [ollamaAvailable, installed])

  const result: SummaryResult | null = summaryQuery.data ?? null
  const showResult = result !== null && !busy

  const submit = async (regenerate: boolean) => {
    setError(null)
    try {
      if (regenerate) {
        // flush pending edits first so the summary matches what the user sees
        const saved = await onBeforeSummarize()
        if (!saved) throw new Error('Could not save pending edits. Try again.')
      }
      await summarize.mutateAsync({ jobId, payload: { model, language } })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Summary failed')
    }
  }

  const copySummary = async () => {
    if (!result) return
    const text =
      result.summary +
      (result.key_points.length
        ? '\n\n' +
          result.key_points
            .map(
              (p) =>
                `- ${p.time_ms != null ? `[${formatDuration(p.time_ms)}] ` : ''}${p.text}`,
            )
            .join('\n')
        : '')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Could not copy — select the text manually instead.')
    }
  }

  return (
    <Modal open title="Video summary" onClose={busy ? () => undefined : onClose} hideClose={busy}>
      {busy ? (
        <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
          <span className="relative flex h-10 w-10 items-center justify-center">
            <Sparkles size={18} className="animate-pulse text-accent" />
          </span>
          <p className="text-sm font-medium">Summarising the video…</p>
          <p className="text-xs text-muted">
            {model} · local Ollama · long videos are processed in chunks, this
            can take a few minutes
          </p>
        </div>
      ) : showResult && result ? (
        <div className="animate-fade-in space-y-4">
          <p className="flex items-center gap-2 text-xs text-muted">
            <ListTree size={14} className="shrink-0" />
            {result.model} · {result.cue_count} subtitle
            {result.cue_count === 1 ? '' : 's'} ·{' '}
            {result.language === 'th' ? 'Thai' : 'English'} · click a point to
            jump there
          </p>

          <p className="whitespace-pre-line text-sm leading-relaxed">
            {result.summary}
          </p>

          {result.key_points.length > 0 ? (
            <ul className="space-y-1.5">
              {result.key_points.map((point, i) => (
                <li key={i}>
                  <button
                    className="flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-surface-2/60"
                    disabled={point.time_ms == null}
                    onClick={() => {
                      if (point.time_ms != null) {
                        onSeek(point.time_ms)
                        onClose()
                      }
                    }}
                  >
                    {point.time_ms != null ? (
                      <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-accent">
                        <Play size={10} />
                        {formatDuration(point.time_ms)}
                      </span>
                    ) : (
                      <span className="shrink-0 font-mono text-[11px] text-muted">—</span>
                    )}
                    <span className="min-w-0 flex-1">{point.text}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {error ? (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
            >
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 break-words">{error}</span>
            </div>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={() => void copySummary()}>
              {copied ? <Check size={15} /> : <Copy size={15} />}{' '}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button variant="secondary" onClick={() => void submit(true)}>
              Regenerate
            </Button>
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      ) : (
        <div className="animate-fade-in space-y-4">
          <p className="flex items-center gap-2 text-xs text-muted">
            <ListTree size={14} className="shrink-0" />
            Generate a summary + key points from the saved subtitles — local
            Ollama, free, nothing leaves your machine.
          </p>

          {info.isLoading ? (
            <div className="flex items-center justify-center gap-2 p-6 text-sm text-muted">
              <Spinner /> Checking Ollama…
            </div>
          ) : info.isError ? (
            <div className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              Could not check Ollama. Is the backend running?
            </div>
          ) : ollamaAvailable ? (
            <Field label="Model" hint="Installed models come from your Ollama server">
              <select
                className={inputClass}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {installed.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                {!installed.includes(model) ? (
                  <option value={model}>{model} (not installed)</option>
                ) : null}
              </select>
            </Field>
          ) : (
            <div className="flex items-start gap-2.5 rounded-lg border border-warning/40 bg-warning/5 px-3.5 py-3 text-sm text-warning">
              <Info size={15} className="mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="font-medium">Ollama is not reachable.</p>
                <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-xs text-warning/90">
                  <li>
                    Install Ollama from{' '}
                    <a
                      href="https://ollama.com"
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      ollama.com
                    </a>{' '}
                    and start it.
                  </li>
                  <li>
                    <code className="font-mono">ollama pull qwen2.5:7b</code> (or any
                    Thai-capable instruct model).
                  </li>
                  <li>
                    Non-default server or model? Set <code className="font-mono">OLLAMA_URL</code>{' '}
                    / <code className="font-mono">OLLAMA_SUMMARY_MODEL</code> in{' '}
                    <code className="font-mono">.env</code> and restart the backend.
                  </li>
                </ol>
              </div>
            </div>
          )}

          <Field label="Output language">
            <div className="flex gap-1.5">
              {(['th', 'en'] as const).map((code) => (
                <button
                  key={code}
                  type="button"
                  aria-pressed={language === code}
                  onClick={() => setLanguage(code)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                    language === code
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-line text-muted hover:border-accent/50 hover:text-text'
                  }`}
                >
                  {code === 'th' ? 'ไทย' : 'English'}
                </button>
              ))}
            </div>
          </Field>

          {error ? (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
            >
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 break-words">{error}</span>
            </div>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => void submit(false)} disabled={!ollamaAvailable || !model}>
              <Sparkles size={15} /> Generate
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
