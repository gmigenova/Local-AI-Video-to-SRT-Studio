// Last-used transcription settings, persisted for convenience (§11.3).
// No translation options, no speaker identification (spec §11.3).

import { create } from 'zustand'

export type QualityPreset = 'high' | 'balanced' | 'fast'

const PRESETS: Record<QualityPreset, { model: string; beam: number }> = {
  high: { model: 'large-v3', beam: 5 },
  balanced: { model: 'large-v3-turbo', beam: 5 },
  fast: { model: 'large-v3-turbo', beam: 1 },
}

export interface ResolvedSettings {
  model: string
  language: string | null
  settings: {
    beam_size: number
    vad_filter: boolean
    word_timestamps: boolean
    condition_on_previous_text: boolean
    initial_prompt: string | null
    vad_threshold?: number
    vad_min_silence_ms?: number
  }
}

interface SettingsState {
  model: string
  language: string | null
  quality: QualityPreset
  beamSize: number
  vad: boolean
  wordTimestamps: boolean
  conditionOnPrevText: boolean
  initialPrompt: string
  vadThreshold: string
  vadMinSilenceMs: string
  setQuality: (quality: QualityPreset) => void
  patch: (update: Partial<Omit<SettingsState, 'patch' | 'setQuality' | 'resolved'>>) => void
  resolved: () => ResolvedSettings
}

function loadDefaults(): Partial<SettingsState> {
  try {
    const raw = localStorage.getItem('v2srt-settings')
    if (raw) return JSON.parse(raw) as Partial<SettingsState>
  } catch {
    /* ignore */
  }
  return {}
}

const stored = loadDefaults()

function persist(state: SettingsState): void {
  try {
    localStorage.setItem(
      'v2srt-settings',
      JSON.stringify({
        model: state.model,
        language: state.language,
        quality: state.quality,
        beamSize: state.beamSize,
        vad: state.vad,
        wordTimestamps: state.wordTimestamps,
        conditionOnPrevText: state.conditionOnPrevText,
        initialPrompt: state.initialPrompt,
        vadThreshold: state.vadThreshold,
        vadMinSilenceMs: state.vadMinSilenceMs,
      }),
    )
  } catch {
    /* ignore */
  }
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  model: stored.model ?? 'large-v3',
  language: stored.language ?? null,
  quality: stored.quality ?? 'high',
  beamSize: stored.beamSize ?? 5,
  vad: stored.vad ?? true,
  wordTimestamps: stored.wordTimestamps ?? true,
  conditionOnPrevText: stored.conditionOnPrevText ?? false,
  initialPrompt: stored.initialPrompt ?? '',
  vadThreshold: stored.vadThreshold ?? '',
  vadMinSilenceMs: stored.vadMinSilenceMs ?? '',

  setQuality: (quality) => {
    const preset = PRESETS[quality]
    set({ quality, model: preset.model, beamSize: preset.beam })
    persist(get())
  },

  patch: (update) => {
    set(update)
    persist(get())
  },

  resolved: () => {
    const s = get()
    const vadThreshold = Number.parseFloat(s.vadThreshold)
    const vadMinSilenceMs = Number.parseInt(s.vadMinSilenceMs, 10)
    return {
      model: s.model,
      language: s.language,
      settings: {
        beam_size: s.beamSize,
        vad_filter: s.vad,
        word_timestamps: s.wordTimestamps,
        condition_on_previous_text: s.conditionOnPrevText,
        initial_prompt: s.initialPrompt.trim() ? s.initialPrompt.trim() : null,
        ...(Number.isFinite(vadThreshold) ? { vad_threshold: vadThreshold } : {}),
        ...(Number.isFinite(vadMinSilenceMs) ? { vad_min_silence_ms: vadMinSilenceMs } : {}),
      },
    }
  },
}))
