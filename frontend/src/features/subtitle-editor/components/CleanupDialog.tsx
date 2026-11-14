// AI cleanup dialog: proofread the whole subtitle list with a local Ollama
// model — punctuation, casing, filler words, Thai polish. The cleaned texts
// are applied as one undo step; timestamps are never touched.

import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, Sparkles, Wand2 } from 'lucide-react'

import { api } from '../../../api/client'
import { useTranslationInfo } from '../../../api/hooks'
import type { CleanupMode, CleanupResult } from '../../../types'
import { Button, Field, Modal, Spinner, inputClass } from '../../../components/ui'

/** idle = form, cleaning = in-flight, success = beat before close */
type Phase = 'idle' | 'cleaning' | 'success'

const MODE_OPTIONS: { id: CleanupMode; label: string; description: string }[] = [
  {
    id: 'punctuation',
    label: 'Punctuation',
    description: 'Add missing commas, periods, question marks',
  },
  {
    id: 'casing',
    label: 'Casing',
    description: 'Capitalise sentence starts and proper nouns',
  },
  {
    id: 'fillers',
    label: 'Remove fillers',
    description: 'Drop "um", "uh", stutters, repeated words',
  },
  {
    id: 'fluency',
    label: 'Fluency',
    description: 'Smooth awkward transcription phrasing',
  },
  {
    id: 'thai_polish',
    label: 'Thai polish',
    description: 'Fix Thai spacing and word boundaries for readability',
  },
]

/** Preferred cleanup default when several models are installed. */
const PREFERRED_MODEL_HINT = 'qwen'

interface CleanupDialogProps {
  jobId: string
  subtitleCount: number
  /** Flush pending editor edits so the server cleans the latest text. */
  onBeforeCleanup: () => Promise<boolean>
  onApply: (result: CleanupResult) => void
  onClose: () => void
}

export default function CleanupDialog({
  jobId,
  subtitleCount,
  onBeforeCleanup,
  onApply,
  onClose,
}: CleanupDialogProps) {
  const info = useTranslationInfo()
  const ollama = info.data?.engines?.ollama
  const ollamaAvailable = ollama?.available ?? false
  const installed = useMemo(() => ollama?.models ?? [], [ollama])

  const [model, setModel] = useState<string>(
    installed.find((name) => name.includes(PREFERRED_MODEL_HINT)) ?? installed[0] ?? 'qwen2.5:7b',
  )
  const [modes, setModes] = useState<CleanupMode[]>(['punctuation', 'thai_polish'])
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const busy = phase !== 'idle'

  // default model arrives with the engine status (after first render)
  useEffect(() => {
    if (ollamaAvailable && installed.length > 0) {
      setModel((m) =>
        installed.includes(m)
          ? m
          : (installed.find((name) => name.includes(PREFERRED_MODEL_HINT)) ?? installed[0] ?? m),
      )
    }
  }, [ollamaAvailable, installed])

  // the success beat awaits before calling onApply — skip the call if the
  // dialog unmounted meanwhile
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const toggleMode = (mode: CleanupMode) => {
    setModes((current) =>
      current.includes(mode) ? current.filter((m) => m !== mode) : [...current, mode],
    )
  }

  const submit = async () => {
    setError(null)
    setPhase('cleaning')
    try {
      // flush pending edits first so the cleanup matches what the user sees
      const saved = await onBeforeCleanup()
      if (!saved) throw new Error('Could not save pending edits. Try again.')
      const result = await api.cleanupSubtitles(jobId, { modes, model })
      setPhase('success')
      await new Promise((resolve) => setTimeout(resolve, 600))
      if (alive.current) onApply(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cleanup failed')
      setPhase('idle')
    }
  }

  const modelInstalled = installed.includes(model)
  const canSubmit = !busy && modes.length > 0 && !!model

  return (
    <Modal
      open
      title="AI cleanup"
      onClose={busy ? () => undefined : onClose}
      hideClose={busy}
    >
      {phase !== 'idle' ? (
        <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
          {phase === 'cleaning' ? (
            <>
              <span className="relative flex h-10 w-10 items-center justify-center">
                <Sparkles size={18} className="animate-pulse text-accent" />
              </span>
              <p className="text-sm font-medium">Cleaning {subtitleCount} subtitles…</p>
              <p className="text-xs text-muted">
                {model} · {modes.length} mode{modes.length === 1 ? '' : 's'} · local Ollama, no
                data leaves your machine
              </p>
            </>
          ) : (
            <>
              <CheckCircle2 size={36} className="text-success" />
              <p className="text-sm font-medium">Done — applying to the editor…</p>
            </>
          )}
        </div>
      ) : (
        <div className="animate-fade-in space-y-4">
          <p className="flex items-center gap-2 text-xs text-muted">
            <Wand2 size={14} className="shrink-0" />
            Ollama · {model} · {subtitleCount} subtitle{subtitleCount === 1 ? '' : 's'} · undo
            with Ctrl+Z
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
                disabled={busy}
              >
                {installed.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                {!modelInstalled ? (
                  <option value={model}>{model} (not installed)</option>
                ) : null}
              </select>
              {!modelInstalled ? (
                <p className="mt-1 text-xs text-warning">
                  Run <code className="font-mono">ollama pull {model}</code> to install this
                  model first.
                </p>
              ) : null}
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
                    <code className="font-mono">ollama pull qwen2.5:7b</code> (or any Thai-capable
                    instruct model).
                  </li>
                  <li>
                    Non-default server or model? Set <code className="font-mono">OLLAMA_URL</code>{' '}
                    / <code className="font-mono">OLLAMA_CLEANUP_MODEL</code> in{' '}
                    <code className="font-mono">.env</code> and restart the backend.
                  </li>
                </ol>
              </div>
            </div>
          )}

          <Field label="What to fix" hint="Text only — timing is never touched">
            <div className="flex flex-wrap gap-1.5">
              {MODE_OPTIONS.map((option) => {
                const active = modes.includes(option.id)
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => toggleMode(option.id)}
                    disabled={busy}
                    title={option.description}
                    aria-pressed={active}
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                      active
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-line text-muted hover:border-accent/50 hover:text-text'
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
            {modes.length === 0 ? (
              <p className="mt-1.5 text-xs text-warning">Pick at least one fix.</p>
            ) : null}
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
            <Button onClick={() => void submit()} disabled={!canSubmit}>
              <Wand2 size={15} /> Clean up
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
