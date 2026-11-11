// Transcription settings form (§11.3): model, language, quality, advanced.
// No translation, no speaker identification (spec).

import { useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'

import { useSettingsStore } from '../stores/settings'
import { Button, Field, inputClass } from './ui'

const LANGUAGES: { value: string; label: string }[] = [
  { value: '', label: 'Auto-detect' },
  { value: 'th', label: 'Thai' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: 'Japanese' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ko', label: 'Korean' },
  { value: 'de', label: 'German' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'ru', label: 'Russian' },
  { value: 'hi', label: 'Hindi' },
  { value: 'id', label: 'Indonesian' },
  { value: 'vi', label: 'Vietnamese' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'it', label: 'Italian' },
  { value: 'ar', label: 'Arabic' },
]

export default function TranscriptionSettingsForm({
  onSubmit,
  onCancel,
  submitting = false,
  submitLabel = 'Start transcription',
}: {
  onSubmit: () => void
  onCancel: () => void
  submitting?: boolean
  submitLabel?: string
}) {
  const store = useSettingsStore()
  const [advanced, setAdvanced] = useState(false)

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <Field label="Quality preset">
        <div className="grid grid-cols-3 gap-2">
          {(['high', 'balanced', 'fast'] as const).map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => store.setQuality(q)}
              className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                store.quality === q
                  ? 'border-accent bg-accent/10'
                  : 'border-line hover:bg-surface-2'
              }`}
            >
              <span className="block text-sm font-medium capitalize">{q}</span>
              <span className="block text-[11px] text-muted">
                {q === 'high'
                  ? 'large-v3 · beam 5'
                  : q === 'balanced'
                    ? 'turbo · beam 5'
                    : 'turbo · beam 1'}
              </span>
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Model">
          <select
            className={inputClass}
            value={store.model}
            onChange={(e) => store.patch({ model: e.target.value })}
          >
            <option value="large-v3">large-v3 (best accuracy)</option>
            <option value="large-v3-turbo">large-v3-turbo (faster)</option>
          </select>
        </Field>
        <Field label="Language">
          <select
            className={inputClass}
            value={store.language ?? ''}
            onChange={(e) => store.patch({ language: e.target.value || null })}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <button
        type="button"
        onClick={() => setAdvanced((v) => !v)}
        className="flex items-center gap-1 text-xs font-medium text-muted transition-colors hover:text-text"
      >
        {advanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        Advanced
      </button>

      {advanced ? (
        <div className="space-y-4 rounded-lg border border-line bg-surface-2/50 p-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Beam size" hint="Higher = more accurate, slower">
              <input
                type="number"
                min={1}
                max={10}
                className={inputClass}
                value={store.beamSize}
                onChange={(e) => store.patch({ beamSize: Number(e.target.value) || 1 })}
              />
            </Field>
          </div>
          <div className="space-y-2.5">
            <label className="flex items-center gap-2.5 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
                checked={store.vad}
                onChange={(e) => store.patch({ vad: e.target.checked })}
              />
              Voice activity detection (VAD)
            </label>
            <label className="flex items-center gap-2.5 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
                checked={store.wordTimestamps}
                onChange={(e) => store.patch({ wordTimestamps: e.target.checked })}
              />
              Word-level timestamps
            </label>
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
                checked={store.conditionOnPrevText}
                onChange={(e) => store.patch({ conditionOnPrevText: e.target.checked })}
              />
              <span>
                Carry context between segments
                <span className="block text-[11px] text-muted">
                  Can make subtitles drift after long silences — leave off for long
                  videos
                </span>
              </span>
            </label>
          </div>
          {store.vad ? (
            <div className="grid grid-cols-2 gap-4">
              <Field label="VAD threshold" hint="0.5 = default; higher filters more quiet noise">
                <input
                  type="number"
                  min={0.1}
                  max={0.9}
                  step={0.05}
                  className={inputClass}
                  placeholder="0.5"
                  value={store.vadThreshold}
                  onChange={(e) => store.patch({ vadThreshold: e.target.value })}
                />
              </Field>
              <Field label="Min silence (ms)" hint="2000 = default; split at longer quiet gaps">
                <input
                  type="number"
                  min={0}
                  step={100}
                  className={inputClass}
                  placeholder="2000"
                  value={store.vadMinSilenceMs}
                  onChange={(e) => store.patch({ vadMinSilenceMs: e.target.value })}
                />
              </Field>
            </div>
          ) : null}
          <Field label="Initial prompt" hint="Optional vocabulary hint for the model">
            <input
              type="text"
              className={inputClass}
              placeholder="e.g. names, technical terms…"
              value={store.initialPrompt}
              onChange={(e) => store.patch({ initialPrompt: e.target.value })}
            />
          </Field>
        </div>
      ) : null}

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting}>
          <Sparkles size={15} />
          {submitting ? 'Starting…' : submitLabel}
        </Button>
      </div>
    </form>
  )
}
