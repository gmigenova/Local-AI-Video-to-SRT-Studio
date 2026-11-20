// Low-confidence word highlighting: transcript.json stores a probability
// per word; words the transcription model was unsure about are surfaced in
// the editor so the user knows where to proofread. Everything here is pure
// — mapping is by time overlap, so rows whose times no longer match the
// transcript (edited / shifted / imported) simply get no highlights.

import type { TranscriptSegment } from '../../types'

/** Whisper word probabilities run ~0.85-0.95 when healthy; below 0.6 the
 *  decode is genuinely shaky. Fixed default, not a user setting. */
export const LOW_CONFIDENCE_THRESHOLD = 0.6

export interface RiskyWord {
  word: string
  probability: number
}

interface TimeRange {
  key: string
  start_ms: number
  end_ms: number
}

/** Map low-confidence transcript words to the row they overlap the most
 *  (mirrors the diarization alignment approach). Words that overlap no row
 *  are dropped. Single sweep: both words and rows are time-ordered. */
export function mapWordsToRows(
  rows: TimeRange[],
  segments: TranscriptSegment[],
  threshold: number = LOW_CONFIDENCE_THRESHOLD,
): Map<string, RiskyWord[]> {
  const result = new Map<string, RiskyWord[]>()
  if (rows.length === 0 || segments.length === 0) return result

  // rows sorted by start; keys kept so unsorted editor rows still map back
  const sortedRows = [...rows].sort((a, b) => a.start_ms - b.start_ms)
  let cursor = 0 // rows entirely before the current word can be skipped

  for (const segment of segments) {
    for (const w of segment.words) {
      if (w.probability === null || w.probability >= threshold) continue
      const token = w.word.trim()
      if (!token) continue

      // drop rows that end before this word starts — they cannot overlap
      // this word nor any later one (words arrive in time order)
      while (
        cursor < sortedRows.length &&
        sortedRows[cursor].end_ms <= w.start_ms
      ) {
        cursor++
      }

      let bestKey: string | null = null
      let bestOverlap = 0
      for (let i = cursor; i < sortedRows.length; i++) {
        const row = sortedRows[i]
        if (row.start_ms >= w.end_ms) break // rows are start-sorted: done
        const overlap =
          Math.min(w.end_ms, row.end_ms) - Math.max(w.start_ms, row.start_ms)
        if (overlap > bestOverlap) {
          bestOverlap = overlap
          bestKey = row.key
        }
      }

      if (bestKey !== null) {
        const list = result.get(bestKey)
        const risky: RiskyWord = { word: token, probability: w.probability }
        if (list) list.push(risky)
        else result.set(bestKey, [risky])
      }
    }
  }
  return result
}

export interface TextChunk {
  text: string
  risky: boolean
}

/** Split row text into plain/risky chunks by locating each risky token in
 *  order. Tokens that no longer appear (the text was edited, merged…) are
 *  skipped — a degraded row shows no highlight rather than a wrong one. */
export function confidenceChunks(text: string, risky: RiskyWord[]): TextChunk[] {
  if (!text || risky.length === 0) return [{ text, risky: false }]

  const chunks: TextChunk[] = []
  let cursor = 0
  for (const { word } of risky) {
    const found = text.indexOf(word, cursor)
    if (found === -1) continue
    if (found > cursor) chunks.push({ text: text.slice(cursor, found), risky: false })
    chunks.push({ text: text.slice(found, found + word.length), risky: true })
    cursor = found + word.length
  }
  if (cursor < text.length) chunks.push({ text: text.slice(cursor), risky: false })
  return chunks
}
