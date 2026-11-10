// Formatting helpers shared across pages.

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '--:--'
  const totalSeconds = Math.floor(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

/** ms -> SRT-style timestamp for display: HH:MM:SS,mmm */
export function formatTimestamp(ms: number): string {
  const clamped = Math.max(0, Math.round(ms))
  const hours = Math.floor(clamped / 3_600_000)
  const minutes = Math.floor((clamped % 3_600_000) / 60_000)
  const seconds = Math.floor((clamped % 60_000) / 1000)
  const millis = clamped % 1000
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)},${String(millis).padStart(3, '0')}`
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

const LANGUAGE_NAMES: Record<string, string> = {
  th: 'Thai',
  en: 'English',
  ja: 'Japanese',
  zh: 'Chinese',
  ko: 'Korean',
  de: 'German',
  fr: 'French',
  es: 'Spanish',
  ru: 'Russian',
  hi: 'Hindi',
  id: 'Indonesian',
  vi: 'Vietnamese',
  pt: 'Portuguese',
  it: 'Italian',
  ar: 'Arabic',
}

export function languageName(code: string | null | undefined): string {
  if (!code) return 'Auto-detect'
  return LANGUAGE_NAMES[code] ?? code.toUpperCase()
}

export function elapsedSince(iso: string | null): number {
  if (!iso) return 0
  return Math.max(0, Date.now() - new Date(iso).getTime())
}

export function formatElapsed(ms: number): string {
  return formatDuration(ms)
}
