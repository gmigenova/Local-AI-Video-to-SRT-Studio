// Client-side quality checks (§11.6), mirroring the backend defaults (§6.1).
// Warnings are advisory — the user fixes them manually.

export const EDITOR_RULES = {
  minDurationMs: 800,
  maxDurationMs: 7000,
  maxCharsPerLine: 42,
  maxLines: 2,
  maxReadingSpeed: 20, // chars/second
  gapMs: 50,
}

export interface EditorSubtitleLite {
  key: string
  start_ms: number
  end_ms: number
  text: string
}

export interface SubtitleIssue {
  code: string
  message: string
}

export function checkSubtitles(
  subs: EditorSubtitleLite[],
): Map<string, SubtitleIssue[]> {
  const result = new Map<string, SubtitleIssue[]>()
  const add = (key: string, code: string, message: string) => {
    const list = result.get(key) ?? []
    list.push({ code, message })
    result.set(key, list)
  }

  for (let i = 0; i < subs.length; i++) {
    const sub = subs[i]
    const flat = sub.text.replace(/\n/g, ' ')
    const duration = sub.end_ms - sub.start_ms
    const lines = sub.text.split('\n')

    if (!flat.trim()) add(sub.key, 'EMPTY_TEXT', 'Subtitle text is empty.')
    if (sub.end_ms <= sub.start_ms || sub.start_ms < 0)
      add(sub.key, 'INVALID_TIMESTAMP', 'End time must be after start time.')
    if (i > 0) {
      const prev = subs[i - 1]
      if (sub.start_ms < prev.end_ms + EDITOR_RULES.gapMs)
        add(sub.key, 'OVERLAP', `Starts before line ${i} ends.`)
    }
    if (duration < EDITOR_RULES.minDurationMs)
      add(
        sub.key,
        'TOO_SHORT',
        `On screen for ${Math.round(duration)} ms — below the ${EDITOR_RULES.minDurationMs} ms minimum.`,
      )
    if (duration > EDITOR_RULES.maxDurationMs)
      add(sub.key, 'TOO_LONG', `Longer than ${EDITOR_RULES.maxDurationMs / 1000} s.`)
    if (lines.some((line) => line.length > EDITOR_RULES.maxCharsPerLine))
      add(
        sub.key,
        'LINE_TOO_LONG',
        `A line exceeds ${EDITOR_RULES.maxCharsPerLine} characters.`,
      )
    if (lines.length > EDITOR_RULES.maxLines)
      add(sub.key, 'TOO_MANY_LINES', `Needs ${lines.length} lines (limit ${EDITOR_RULES.maxLines}).`)
    if (duration > 0 && flat.trim().length / (duration / 1000) > EDITOR_RULES.maxReadingSpeed)
      add(
        sub.key,
        'FAST_READING',
        `Reading speed above ${EDITOR_RULES.maxReadingSpeed} characters/second.`,
      )
  }
  return result
}

export const ISSUE_LABELS: Record<string, string> = {
  EMPTY_TEXT: 'Empty text',
  INVALID_TIMESTAMP: 'Invalid timestamps',
  OVERLAP: 'Overlap',
  TOO_SHORT: 'Too short',
  TOO_LONG: 'Long display',
  LINE_TOO_LONG: 'Long line',
  TOO_MANY_LINES: 'Too many lines',
  FAST_READING: 'Fast reading',
}
