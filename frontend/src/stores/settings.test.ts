// Store tests: persistence round-trip + resolved() mapping for the
// last-used transcription settings (§11.3).

import { beforeEach, describe, expect, it } from 'vitest'

import { useSettingsStore } from './settings'

function readStored(): Record<string, unknown> {
  return JSON.parse(localStorage.getItem('v2srt-settings') ?? '{}') as Record<string, unknown>
}

beforeEach(() => {
  localStorage.clear()
  // the store is a module-level singleton — reset it between tests
  useSettingsStore.setState({
    model: 'large-v3',
    language: null,
    quality: 'high',
    beamSize: 5,
    vad: true,
    wordTimestamps: true,
    conditionOnPrevText: false,
    initialPrompt: '',
    vadThreshold: '',
    vadMinSilenceMs: '',
  })
})

describe('settings store', () => {
  it('starts from defaults', () => {
    const s = useSettingsStore.getState()
    expect(s.model).toBe('large-v3')
    expect(s.quality).toBe('high')
    expect(s.vad).toBe(true)
    expect(s.conditionOnPrevText).toBe(false)
    expect(s.initialPrompt).toBe('')
  })

  it('setQuality applies the preset model + beam and persists', () => {
    useSettingsStore.getState().setQuality('fast')
    const s = useSettingsStore.getState()
    expect(s.quality).toBe('fast')
    expect(s.model).toBe('large-v3-turbo')
    expect(s.beamSize).toBe(1)

    const stored = readStored()
    expect(stored.quality).toBe('fast')
    expect(stored.model).toBe('large-v3-turbo')
  })

  it('patch updates fields and persists them', () => {
    useSettingsStore.getState().patch({ initialPrompt: 'ACME Corp', language: 'th' })
    expect(useSettingsStore.getState().initialPrompt).toBe('ACME Corp')
    expect(readStored().initialPrompt).toBe('ACME Corp')
    expect(readStored().language).toBe('th')
  })

  it('resolved() maps raw form fields onto the API settings shape', () => {
    const { patch } = useSettingsStore.getState()
    patch({ vadThreshold: '0.35', vadMinSilenceMs: '750', initialPrompt: '  ACME  ' })

    const resolved = useSettingsStore.getState().resolved()
    expect(resolved.model).toBe('large-v3')
    expect(resolved.language).toBe(null)
    expect(resolved.settings.vad_threshold).toBe(0.35)
    expect(resolved.settings.vad_min_silence_ms).toBe(750)
    expect(resolved.settings.initial_prompt).toBe('ACME') // trimmed
    expect(resolved.settings.condition_on_previous_text).toBe(false)
  })

  it('resolved() drops non-numeric VAD fields instead of sending NaN', () => {
    useSettingsStore.getState().patch({ vadThreshold: 'abc', vadMinSilenceMs: '' })
    const { settings } = useSettingsStore.getState().resolved()
    expect(settings.vad_threshold).toBeUndefined()
    expect(settings.vad_min_silence_ms).toBeUndefined()
  })

  it('resolved() sends a trimmed empty prompt as null', () => {
    useSettingsStore.getState().patch({ initialPrompt: '   ' })
    expect(useSettingsStore.getState().resolved().settings.initial_prompt).toBe(null)
  })
})
