// Unit tests for the waveform decoder + peak computation (pure functions).

import { describe, expect, it } from 'vitest'

import { computePeaks, parseWavMono16 } from './waveform'

function buildWav(samples: Int16Array, sampleRate = 16000, channels = 1): ArrayBuffer {
  const dataLength = samples.length * 2
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)
  const writeText = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
  }
  writeText(0, 'RIFF')
  view.setUint32(4, 36 + dataLength, true)
  writeText(8, 'WAVE')
  writeText(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2 * channels, true) // byte rate
  view.setUint16(32, 2 * channels, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeText(36, 'data')
  view.setUint32(40, dataLength, true)
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, samples[i], true)
  return buffer
}

describe('parseWavMono16', () => {
  it('decodes s16le samples to floats in [-1, 1]', () => {
    const wav = buildWav(Int16Array.from([0, 16384, -16384, 32767, -32768]))
    const samples = parseWavMono16(wav)
    expect(Array.from(samples)).toEqual([0, 0.5, -0.5, 32767 / 32768, -1])
  })

  it('averages stereo channels down to mono', () => {
    // interleaved stereo: L=0.5, R=-0.5, then L=1, R=1
    const wav = buildWav(Int16Array.from([16384, -16384, 32767, 32767]), 16000, 2)
    const samples = parseWavMono16(wav)
    expect(samples.length).toBe(2)
    expect(samples[0]).toBeCloseTo(0)
    expect(samples[1]).toBeCloseTo(1, 4)
  })

  it('rejects non-RIFF buffers', () => {
    expect(() => parseWavMono16(new ArrayBuffer(8))).toThrow()
    const junk = new ArrayBuffer(100)
    new DataView(junk).setUint32(0, 0x52494646) // "RIFF"-ish but no WAVE
    expect(() => parseWavMono16(junk)).toThrow()
  })

  it('rejects non-PCM audio formats (e.g. IEEE float)', () => {
    const wav = buildWav(Int16Array.from([0, 1]))
    new DataView(wav).setUint16(20, 3, true) // audioFormat = 3
    expect(() => parseWavMono16(wav)).toThrow(/format/)
  })

  it('walks past extra chunks to find the data chunk', () => {
    const base = buildWav(Int16Array.from([16384, -16384]))
    // splice a 4-byte LIST chunk in between fmt and data
    const source = new DataView(base)
    const withList = new ArrayBuffer(base.byteLength + 12)
    const target = new DataView(withList)
    new Uint8Array(withList, 0, 36).set(new Uint8Array(base, 0, 36)) // RIFF..fmt
    target.setUint32(4, source.getUint32(4, true) + 12, true) // RIFF size
    const writeText = (offset: number, text: string) => {
      for (let i = 0; i < text.length; i++) target.setUint8(offset + i, text.charCodeAt(i))
    }
    writeText(36, 'LIST')
    target.setUint32(40, 4, true) // chunk size (word-aligned)
    writeText(44, 'INFO')
    new Uint8Array(withList, 48).set(new Uint8Array(base, 36)) // data chunk + payload
    const samples = parseWavMono16(withList)
    expect(samples.length).toBe(2)
    expect(samples[0]).toBeCloseTo(0.5)
  })
})

describe('computePeaks', () => {
  it('returns a flat envelope for a constant signal', () => {
    const peaks = computePeaks(new Float32Array(100).fill(0.25), 10)
    expect(peaks.min.length).toBe(10)
    expect(Array.from(peaks.min)).toEqual(Array(10).fill(0.25))
    expect(Array.from(peaks.max)).toEqual(Array(10).fill(0.25))
  })

  it('captures full-height swings for an alternating signal', () => {
    const samples = new Float32Array(100)
    for (let i = 0; i < samples.length; i++) samples[i] = i % 2 === 0 ? 1 : -1
    const peaks = computePeaks(samples, 5)
    expect(Array.from(peaks.min)).toEqual(Array(5).fill(-1))
    expect(Array.from(peaks.max)).toEqual(Array(5).fill(1))
  })

  it('clamps the bucket count to the sample count', () => {
    const samples = new Float32Array([0.1, 0.9, -0.5])
    const peaks = computePeaks(samples, 100) // more buckets than samples
    expect(peaks.min.length).toBe(3)
    expect(peaks.max.length).toBe(3)
    expect(peaks.max[1]).toBeCloseTo(0.9, 5)
    expect(peaks.min[2]).toBeCloseTo(-0.5, 5)
  })

  it('handles empty input without crashing', () => {
    const peaks = computePeaks(new Float32Array(0), 10)
    expect(peaks.min.length).toBe(1)
    expect(peaks.min[0]).toBe(0)
  })
})
