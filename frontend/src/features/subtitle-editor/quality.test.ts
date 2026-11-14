// Unit tests for the client-side quality checks (§11.6 defaults).

import { describe, expect, it } from 'vitest'

import {
  checkSubtitles,
  EDITOR_RULES,
  type EditorSubtitleLite,
  type SubtitleIssue,
} from './quality'

function sub(overrides: Partial<EditorSubtitleLite>): EditorSubtitleLite {
  return {
    key: 'k1',
    start_ms: 0,
    end_ms: 2000,
    text: 'Hello',
    ...overrides,
  }
}

function codes(result: Map<string, SubtitleIssue[]>, key = 'k1') {
  return (result.get(key) ?? []).map((i) => i.code)
}

describe('checkSubtitles', () => {
  it('passes a clean subtitle', () => {
    const result = checkSubtitles([sub({ start_ms: 1000, end_ms: 3000, text: 'Hello there' })])
    expect(result.get('k1')).toBeUndefined()
  })

  it('flags empty text', () => {
    const result = checkSubtitles([sub({ text: '   \n  ' })])
    expect(codes(result)).toContain('EMPTY_TEXT')
  })

  it('flags invalid timestamps (end not after start, negative start)', () => {
    expect(codes(checkSubtitles([sub({ start_ms: 2000, end_ms: 2000 })]))).toContain(
      'INVALID_TIMESTAMP',
    )
    expect(codes(checkSubtitles([sub({ start_ms: -1, end_ms: 2000 })]))).toContain(
      'INVALID_TIMESTAMP',
    )
  })

  describe('overlap', () => {
    it('accepts a start exactly at prev end + gap', () => {
      const result = checkSubtitles([
        sub({ key: 'a', end_ms: 5000 }),
        sub({ key: 'b', start_ms: 5000 + EDITOR_RULES.gapMs, end_ms: 7000 }),
      ])
      expect(result.get('b')).toBeUndefined()
    })

    it('flags a start inside the required gap', () => {
      const result = checkSubtitles([
        sub({ key: 'a', end_ms: 5000 }),
        sub({ key: 'b', start_ms: 5000 + EDITOR_RULES.gapMs - 1, end_ms: 7000 }),
      ])
      expect(codes(result, 'b')).toContain('OVERLAP')
    })

    it('never flags the first row for overlap', () => {
      const result = checkSubtitles([sub({ start_ms: 0, end_ms: 2000 })])
      expect(codes(result)).not.toContain('OVERLAP')
    })
  })

  describe('duration bounds', () => {
    it('TOO_SHORT below the minimum and passes exactly at it', () => {
      expect(codes(checkSubtitles([sub({ end_ms: EDITOR_RULES.minDurationMs - 1 })]))).toContain(
        'TOO_SHORT',
      )
      expect(
        checkSubtitles([sub({ end_ms: EDITOR_RULES.minDurationMs })]).get('k1'),
      ).toBeUndefined()
    })

    it('TOO_LONG above the maximum and passes exactly at it', () => {
      expect(
        codes(checkSubtitles([sub({ end_ms: EDITOR_RULES.maxDurationMs + 1 })])),
      ).toContain('TOO_LONG')
      expect(
        checkSubtitles([sub({ end_ms: EDITOR_RULES.maxDurationMs })]).get('k1'),
      ).toBeUndefined()
    })
  })

  describe('line length and count', () => {
    it('LINE_TOO_LONG only past the per-line limit', () => {
      const line = 'x'.repeat(EDITOR_RULES.maxCharsPerLine)
      expect(checkSubtitles([sub({ end_ms: 4000, text: line })]).get('k1')).toBeUndefined()
      expect(codes(checkSubtitles([sub({ end_ms: 4000, text: line + 'x' })]))).toContain(
        'LINE_TOO_LONG',
      )
    })

    it('measures per line, not the flattened text', () => {
      const line = 'x'.repeat(EDITOR_RULES.maxCharsPerLine)
      const result = checkSubtitles([sub({ end_ms: 5000, text: `${line}\n${line}` })])
      expect(result.get('k1')).toBeUndefined() // two legal lines, total 84 chars
    })

    it('TOO_MANY_LINES beyond the line limit', () => {
      const line = 'x'
      expect(
        codes(checkSubtitles([sub({ text: `${line}\n${line}\n${line}` })])),
      ).toContain('TOO_MANY_LINES')
    })
  })

  describe('reading speed', () => {
    it('passes at exactly the limit', () => {
      // 20 chars/s: 40 chars over 2000 ms
      const text = 'x'.repeat(2 * EDITOR_RULES.maxReadingSpeed)
      expect(checkSubtitles([sub({ text })]).get('k1')).toBeUndefined()
    })

    it('flags above the limit', () => {
      const text = 'x'.repeat(2 * EDITOR_RULES.maxReadingSpeed + 1)
      expect(codes(checkSubtitles([sub({ text })]))).toContain('FAST_READING')
    })

    it('skips the check when duration is invalid', () => {
      // duration <= 0 must not produce FAST_READING (avoids div-by-zero weirdness)
      const result = checkSubtitles([sub({ start_ms: 5000, end_ms: 5000, text: 'Hi' })])
      expect(codes(result)).not.toContain('FAST_READING')
    })
  })
})
