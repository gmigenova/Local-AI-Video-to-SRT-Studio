// Time input parsing/formatting for the subtitle editor.
// Editing uses seconds with milliseconds: "83.500"; "1:23.5" is also accepted.

export function msToInput(ms: number): string {
  return (Math.max(0, ms) / 1000).toFixed(3)
}

export function parseTimeInput(value: string): number | null {
  const trimmed = value.trim().replace(',', '.')
  if (!trimmed) return null

  // mm:ss.mmm (or h:mm:ss.mmm)
  if (trimmed.includes(':')) {
    const parts = trimmed.split(':')
    if (parts.length > 3) return null
    let seconds = 0
    for (const part of parts) {
      const n = Number(part)
      if (!Number.isFinite(n) || n < 0) return null
      seconds = seconds * 60 + n
    }
    return Math.round(seconds * 1000)
  }

  const n = Number(trimmed)
  if (!Number.isFinite(n) || n < 0) return null
  return Math.round(n * 1000)
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
