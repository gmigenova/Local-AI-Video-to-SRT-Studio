// Tests for the confidence-highlighting helpers (pure functions).

import { describe, expect, it } from 'vitest'

import type { TranscriptSegment } from '../../types'
import {
  confidenceChunks,
  LOW_CONFIDENCE_THRESHOLD,
  mapWordsToRows,
} from './confidence'

function segment(
  words: { start_ms: number; end_ms: number; word: string; probability: number | null }[],
): TranscriptSegment {
  return {
    start_ms: words[0]?.start_ms ?? 0,
    end_ms: words[words.length - 1]?.end_ms ?? 0,
    text: words.map((w) => w.word).join(' '),
    confidence: null,
    words,
  }
}

const ROWS = [
  { key: 'a', start_ms: 0, end_ms: 2000 },
  { key: 'b', start_ms: 2100, end_ms: 4000 },
]

describe('mapWordsToRows', () => {
  it('assigns each risky word to the row it overlaps the most', () => {
    const segments = [
      segment([
        { start_ms: 100, end_ms: 600, word: 'maybe', probability: 0.4 },
        { start_ms: 2400, end_ms: 2900, word: 'perhaps', probability: 0.5 },
      ]),
    ]
    const map = mapWordsToRows(ROWS, segments)
    expect(map.get('a')).toEqual([{ word: 'maybe', probability: 0.4 }])
    expect(map.get('b')).toEqual([{ word: 'perhaps', probability: 0.5 }])
  })

  it('ignores words at or above the threshold and null probabilities', () => {
    const segments = [
      segment([
        { start_ms: 100, end_ms: 600, word: 'solid', probability: LOW_CONFIDENCE_THRESHOLD },
        { start_ms: 700, end_ms: 900, word: 'strong', probability: 0.99 },
        { start_ms: 1000, end_ms: 1200, word: 'blank', probability: null },
      ]),
    ]
    expect(mapWordsToRows(ROWS, segments).size).toBe(0)
  })

  it('drops words that overlap no row (e.g. rows were shifted away)', () => {
    const segments = [
      segment([{ start_ms: 9000, end_ms: 9500, word: 'orphan', probability: 0.3 }]),
    ]
    expect(mapWordsToRows(ROWS, segments).size).toBe(0)
  })

  it('a word spanning two rows lands in the one with the larger overlap', () => {
    const rows = [
      { key: 'a', start_ms: 0, end_ms: 1600 }, // overlaps the word by 100ms only
      { key: 'b', start_ms: 1500, end_ms: 4000 }, // overlaps by 1100ms
    ]
    const segments = [
      segment([{ start_ms: 1500, end_ms: 2600, word: 'straddler', probability: 0.2 }]),
    ]
    const map = mapWordsToRows(rows, segments)
    expect(map.get('b')).toEqual([{ word: 'straddler', probability: 0.2 }])
    expect(map.has('a')).toBe(false)
  })

  it('returns an empty map when there are no rows or no segments', () => {
    expect(mapWordsToRows([], [segment([])])).toEqual(new Map())
    expect(mapWordsToRows(ROWS, [])).toEqual(new Map())
  })
})

describe('confidenceChunks', () => {
  it('marks risky tokens in spaced text', () => {
    const chunks = confidenceChunks('Hello uncertain world', [
      { word: 'uncertain', probability: 0.4 },
    ])
    expect(chunks).toEqual([
      { text: 'Hello ', risky: false },
      { text: 'uncertain', risky: true },
      { text: ' world', risky: false },
    ])
  })

  it('marks risky slices in Thai text without spaces', () => {
    const chunks = confidenceChunks('สวัสดีครับทุกคน', [
      { word: 'ทุกคน', probability: 0.35 },
    ])
    expect(chunks).toEqual([
      { text: 'สวัสดีครับ', risky: false },
      { text: 'ทุกคน', risky: true },
    ])
  })

  it('marks multiple risky words in order', () => {
    const chunks = confidenceChunks('one two three four', [
      { word: 'two', probability: 0.1 },
      { word: 'four', probability: 0.2 },
    ])
    expect(chunks.filter((c) => c.risky).map((c) => c.text)).toEqual(['two', 'four'])
  })

  it('skips tokens that were edited out instead of highlighting the wrong spot', () => {
    const chunks = confidenceChunks('one three', [
      { word: 'two', probability: 0.1 }, // no longer in the text
      { word: 'three', probability: 0.2 },
    ])
    expect(chunks).toEqual([
      { text: 'one ', risky: false },
      { text: 'three', risky: true },
    ])
  })

  it('handles empty text and empty risky lists', () => {
    expect(confidenceChunks('', [{ word: 'x', probability: 0.1 }])).toEqual([
      { text: '', risky: false },
    ])
    expect(confidenceChunks('plain', [])).toEqual([{ text: 'plain', risky: false }])
  })
})
