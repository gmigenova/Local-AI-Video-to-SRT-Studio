// Translate dialog: pick engine (Ollama TranslateGemma local / Google
// Cloud), source/target language + mode, then translate the whole subtitle
// list (applied as one undo step). Google shows the monthly character
// budget; Ollama is free/local and needs an explicit source language.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Info, Languages } from 'lucide-react'

import { api } from '../../../api/client'
import { useTranslationInfo, useTranslationUsage } from '../../../api/hooks'
import type { TranslationEngineId, TranslateMode, TranslateResult } from '../../../types'
import { Button, Field, Modal, Progress, Spinner, inputClass } from '../../../components/ui'
import { languageName } from '../../../utils/format'
import TranslatingState from './TranslatingState'

/** idle = form, translating = in-flight overlay, success = beat before close */
type Phase = 'idle' | 'translating' | 'success'

interface TranslateDialogProps {
  jobId: string
  subtitleCount: number
  /** Total characters of non-empty subtitle text this request would send. */
  pendingChars: number
  /** Whisper's detected language for the job, used as the default source. */
  detectedLanguage: string | null
  /** Flush pending editor edits so the server translates the latest text. */
  onBeforeTranslate: () => Promise<boolean>
  onApply: (result: TranslateResult) => void
  onClose: () => void
}

export default function TranslateDialog({
  jobId,
  subtitleCount,
  pendingChars,
  detectedLanguage,
  onBeforeTranslate,
  onApply,
  onClose,
}: TranslateDialogProps) {
  const queryClient = useQueryClient()
  const info = useTranslationInfo()
  const usage = useTranslationUsage()
  const languages = useMemo(
    () => [...(info.data?.languages ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [info.data],
  )

  const googleConfigured = info.data?.configured ?? false
  const ollama = info.data?.engines?.ollama
  const ollamaAvailable = ollama?.available ?? false
  const defaultModel = ollama?.model ?? 'translategemma:12b'

  // engine defaults to Ollama (local-first) when reachable
  const [engine, setEngine] = useState<TranslationEngineId>(
    ollamaAvailable ? 'ollama' : 'google',
  )
  const [model, setModel] = useState<string>(defaultModel)
  // default target: Thai unless the video is already Thai, then English
  const [target, setTarget] = useState<string>(detectedLanguage === 'th' ? 'en' : 'th')
  const [source, setSource] = useState<string>(detectedLanguage ?? 'auto')
  const [mode, setMode] = useState<TranslateMode>('replace')
  const [phase, setPhase] = useState<Phase>('idle')
  const [successResult, setSuccessResult] = useState<TranslateResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const busy = phase !== 'idle'

  // the success beat awaits before calling onApply — skip the call if the
  // dialog unmounted meanwhile (route change etc.)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // keep the selects valid once the catalog / engine status loads
  useEffect(() => {
    const langs = info.data?.languages
    if (!langs?.length) return
    const codes = new Set(langs.map((l) => l.code))
    setTarget((t) => (codes.has(t) ? t : codes.has('th') ? 'th' : langs[0]!.code))
    setSource((s) => (s !== 'auto' && !codes.has(s) ? (detectedLanguage ?? 'auto') : s))
  }, [info.data, detectedLanguage])

  // engine/model defaults arrive with the engine status (after first render)
  useEffect(() => {
    if (info.data && ollamaAvailable) {
      setEngine((e) => (e === 'google' ? 'ollama' : e))
      setModel((m) => (m === 'translategemma:12b' && ollama?.model ? ollama.model : m))
    }
  }, [info.data, ollamaAvailable, ollama?.model])

  // TranslateGemma needs an explicit source: never leave it on auto
  const effectiveSource =
    engine === 'ollama' && source === 'auto' ? (detectedLanguage ?? null) : source
  const ollamaMissingSource = engine === 'ollama' && effectiveSource === null

  const submit = async () => {
    setError(null)
    setPhase('translating')
    try {
      // flush pending edits first so the translation matches what the user sees
      const saved = await onBeforeTranslate()
      if (!saved) throw new Error('Could not save pending edits. Try again.')
      const result = await api.translateSubtitles(jobId, {
        engine,
        target_language: target,
        source_language: effectiveSource,
        mode,
        ...(engine === 'ollama' ? { model } : {}),
      })
      if (engine === 'google') {
        void queryClient.invalidateQueries({ queryKey: ['translation-usage'] })
      }
      // short success beat, then hand over to the editor (which closes us)
      setSuccessResult(result)
      setPhase('success')
      await new Promise((resolve) => setTimeout(resolve, 750))
      if (alive.current) onApply(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Translation failed')
      setPhase('idle')
    }
  }

  const used = usage.data?.characters_sent ?? 0
  const limit = usage.data?.monthly_char_limit ?? 0
  // remaining is null only when unlimited (limit = 0)
  const remaining = limit > 0 ? (usage.data?.remaining_chars ?? 0) : null
  const modelInstalled = (ollama?.models ?? []).includes(model)
  const canSubmit =
    !busy && !!target && !ollamaMissingSource && (engine === 'google' || !!model)

  const showGoogleWarning = engine === 'google' && !googleConfigured

  const sourceLabel =
    source === 'auto' && engine === 'google' ? 'Auto-detect' : languageName(effectiveSource)
  const targetLabel = languageName(target)

  return (
    <Modal
      open
      title="Translate subtitles"
      onClose={busy ? () => undefined : onClose}
      hideClose={busy}
    >
      {phase !== 'idle' ? (
        <TranslatingState
          phase={phase}
          engine={engine}
          model={model}
          subtitleCount={subtitleCount}
          sourceLabel={sourceLabel}
          targetLabel={targetLabel}
          result={successResult}
        />
      ) : (
      <div className="animate-fade-in space-y-4">
        <p className="flex items-center gap-2 text-xs text-muted">
          <Languages size={14} className="shrink-0" />
          {engine === 'ollama' ? `Ollama · ${model}` : 'Google Cloud Translation'} ·{' '}
          {subtitleCount} subtitle{subtitleCount === 1 ? '' : 's'}
        </p>

        {info.isLoading ? (
          <div className="flex items-center justify-center gap-2 p-6 text-sm text-muted">
            <Spinner /> Loading languages…
          </div>
        ) : info.isError ? (
          <div className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            Could not load the language list. Is the backend running?
          </div>
        ) : (
          <>
            {/* engine selector */}
            <Field label="Engine">
              <div className="space-y-1.5">
                <ModeOption
                  active={engine === 'ollama'}
                  disabled={busy || !ollamaAvailable}
                  onSelect={() => setEngine('ollama')}
                  title="Ollama (local)"
                  description={
                    ollamaAvailable
                      ? 'TranslateGemma on your machine — free, private'
                      : 'Not reachable — is Ollama running?'
                  }
                />
                <ModeOption
                  active={engine === 'google'}
                  disabled={busy || !googleConfigured}
                  onSelect={() => setEngine('google')}
                  title="Google Cloud Translation"
                  description={
                    googleConfigured
                      ? 'Cloud API — fast, monthly character budget'
                      : 'Not configured — GOOGLE_TRANSLATE_API_KEY is unset'
                  }
                />
              </div>
            </Field>

            {/* Ollama: model picker */}
            {engine === 'ollama' ? (
              ollamaAvailable ? (
                <Field label="Model" hint="Installed models come from your Ollama server">
                  <select
                    className={inputClass}
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    disabled={busy}
                  >
                    {(ollama?.models ?? []).map((name) => (
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
                      Run <code className="font-mono">ollama pull {model}</code> to install
                      this model first.
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
                        <code className="font-mono">ollama pull {defaultModel}</code>
                      </li>
                      <li>
                        Non-default server or model? Set{' '}
                        <code className="font-mono">OLLAMA_URL</code> /{' '}
                        <code className="font-mono">OLLAMA_TRANSLATE_MODEL</code> in{' '}
                        <code className="font-mono">.env</code> and restart the backend.
                      </li>
                    </ol>
                  </div>
                </div>
              )
            ) : null}

            {/* Google: budget box */}
            {engine === 'google' && googleConfigured ? (
              <div className="rounded-lg border border-line bg-surface-2/40 px-3.5 py-2.5 text-xs">
                {limit > 0 ? (
                  <>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted">
                        This month: <b className="text-text">{used.toLocaleString()}</b> /{' '}
                        {limit.toLocaleString()} characters
                      </span>
                      <span
                        className={
                          remaining !== null && remaining < pendingChars
                            ? 'font-medium text-danger'
                            : 'text-muted'
                        }
                      >
                        {remaining !== null ? remaining.toLocaleString() : '—'} left
                      </span>
                    </div>
                    <Progress value={(used / limit) * 100} />
                  </>
                ) : (
                  <p className="text-muted">
                    This month: <b className="text-text">{used.toLocaleString()}</b>{' '}
                    characters (no limit set)
                  </p>
                )}
                <p className="mt-1.5 text-muted/80">
                  This request sends ~{pendingChars.toLocaleString()} characters
                  {remaining !== null && remaining < pendingChars
                    ? ' — over the remaining budget, it will be rejected'
                    : ''}
                  {' '}· {(usage.data?.words_sent ?? 0).toLocaleString()} words translated so
                  far
                </p>
              </div>
            ) : null}

            {/* Google not configured hint */}
            {showGoogleWarning ? (
              <div className="flex items-start gap-2.5 rounded-lg border border-warning/40 bg-warning/5 px-3.5 py-3 text-sm text-warning">
                <Info size={15} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <p className="font-medium">Google Cloud Translation is not configured.</p>
                  <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-xs text-warning/90">
                    <li>
                      In Google Cloud Console enable the <b>Cloud Translation API</b> and
                      create an API key (APIs &amp; Services → Credentials).
                    </li>
                    <li>
                      Paste it into <code className="font-mono">GOOGLE_TRANSLATE_API_KEY</code>{' '}
                      in the <code className="font-mono">.env</code> file.
                    </li>
                    <li>Restart the backend, then reopen this dialog.</li>
                  </ol>
                </div>
              </div>
            ) : null}

            {/* languages */}
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Translate from"
                hint={
                  engine === 'ollama' && source === 'auto' && detectedLanguage
                    ? `Auto is not supported here — using the detected language (${detectedLanguage})`
                    : undefined
                }
              >
                <select
                  className={inputClass}
                  value={effectiveSource ?? ''}
                  onChange={(e) => setSource(e.target.value)}
                  disabled={busy}
                >
                  {engine === 'google' ? <option value="auto">Auto-detect</option> : null}
                  {languages.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Translate to">
                <select
                  className={inputClass}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={busy}
                >
                  {languages.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            {ollamaMissingSource ? (
              <p className="text-xs text-warning">
                Ollama needs an explicit source language — this job has no detected
                language. Pick one above.
              </p>
            ) : null}

            <Field label="Result">
              <div className="space-y-1.5">
                <ModeOption
                  active={mode === 'replace'}
                  disabled={busy}
                  onSelect={() => setMode('replace')}
                  title="Replace text"
                  description="The translated text replaces each subtitle (undo with Ctrl+Z)"
                />
                <ModeOption
                  active={mode === 'dual'}
                  disabled={busy}
                  onSelect={() => setMode('dual')}
                  title="Bilingual (original + translation)"
                  description="The translation is added on a new line below the original text"
                />
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
              <Button onClick={() => void submit()} disabled={!canSubmit}>
                <Languages size={15} /> Translate
              </Button>
            </div>
          </>
        )}
      </div>
      )}
    </Modal>
  )
}

function ModeOption({
  active,
  disabled,
  onSelect,
  title,
  description,
}: {
  active: boolean
  disabled?: boolean
  onSelect: () => void
  title: string
  description: string
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      className={`flex w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
        active
          ? 'border-accent bg-accent/10'
          : 'border-line hover:border-accent/50 hover:bg-surface-2/50'
      } disabled:cursor-not-allowed disabled:opacity-50`}
      aria-pressed={active}
    >
      <span
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
          active ? 'border-accent bg-accent text-accent-text' : 'border-line'
        }`}
      >
        {active ? <Check size={11} strokeWidth={3} /> : null}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted">{description}</span>
      </span>
    </button>
  )
}
