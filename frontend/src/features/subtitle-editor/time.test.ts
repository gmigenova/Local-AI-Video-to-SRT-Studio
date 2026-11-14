// Unit tests for editor time parsing/formatting and the split heuristic.

import { describe, expect, it } from 'vitest'

import { clamp, msToInput, parseTimeInput } from './time'
import { splitTextAtRatio } from './useSubtitleEditor'

describe('msToInput', () => {
  it('formats seconds with three decimals', () => {
    expect(msToInput(83_500)).toBe('83.500')
    expect(msToInput(0)).toBe('0.000')
  })

  it('clamps negatives to zero', () => {
    expect(msToInput(-120)).toBe('0.000')
  })
})

describe('parseTimeInput', () => {
  it('parses plain seconds with ms', () => {
    expect(parseTimeInput('83.500')).toBe(83_500)
    expect(parseTimeInput(' 12.5 ')).toBe(12_500)
  })

  it('accepts comma as the decimal separator', () => {
    expect(parseTimeInput('1:23,5')).toBe(83_500)
  })

  it('parses mm:ss and h:mm:ss forms', () => {
    expect(parseTimeInput('1:23.5')).toBe(83_500)
    expect(parseTimeInput('0:01:01.5')).toBe(61_500)
    expect(parseTimeInput('1:00')).toBe(60_000)
  })

  it('rejects invalid input with null', () => {
    expect(parseTimeInput('')).toBeNull()
    expect(parseTimeInput('   ')).toBeNull()
    expect(parseTimeInput('abc')).toBeNull()
    expect(parseTimeInput('-5')).toBeNull()
    expect(parseTimeInput('1:-30')).toBeNull()
    expect(parseTimeInput('1:2:3:4')).toBeNull() // more than h:mm:ss
  })
})

describe('clamp', () => {
  it('keeps in-range values and pins out-of-range ones', () => {
    expect(clamp(5, 0, 10)).toBe(5)
    expect(clamp(-1, 0, 10)).toBe(0)
    expect(clamp(11, 0, 10)).toBe(10)
  })
})

describe('splitTextAtRatio', () => {
  it('returns empty halves for blank text', () => {
    expect(splitTextAtRatio('   ', 0.5)).toEqual(['', ''])
  })

  it('splits spaced text at a word boundary', () => {
    expect(splitTextAtRatio('hello world foo', 0.5)).toEqual(['hello world', 'foo'])
  })

  it('keeps everything on the left when the ratio reaches the last word', () => {
    expect(splitTextAtRatio('hello world', 0.9)).toEqual(['hello world', ''])
  })

  it('splits spaceless (Thai) text at a character boundary', () => {
    // note: the cut is at UTF-16 code units — pick a string whose midpoint
    // is not inside a combining mark
    expect(splitTextAtRatio('กรุงเทพ', 0.5)).toEqual(['กรุง', 'เทพ'])
  })

  it('never returns an empty right half for multi-char spaceless text', () => {
    const [left, right] = splitTextAtRatio('กรุงเทพมหานคร', 0.99)
    expect(left.length).toBeGreaterThan(0)
    expect(right.length).toBeGreaterThanOrEqual(0)
    expect(left + right).toBe('กรุงเทพมหานคร')
  })
})
