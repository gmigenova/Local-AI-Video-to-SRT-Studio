// Loads the job's extracted audio once and reduces it to waveform peaks.
// 404 (retention removed the file) and network failures degrade to
// 'unavailable' — the timeline simply keeps its plain background.

import { useEffect, useState } from 'react'

import { computePeaks, parseWavMono16, type WaveformPeaks } from './waveform'

export type WaveformStatus = 'loading' | 'ready' | 'unavailable'

/** Buckets for the whole-video envelope; rendering maps them to pixels. */
const PEAK_BUCKETS = 4000

/** Decoded samples cached per URL — editor re-renders never refetch. */
const samplesCache = new Map<string, Promise<Float32Array>>()

async function loadSamples(url: string, signal: AbortSignal): Promise<Float32Array> {
  const cached = samplesCache.get(url)
  if (cached) return cached

  const pending = (async () => {
    const response = await fetch(url, { signal })
    if (!response.ok) throw new Error(`audio fetch failed: ${response.status}`)
    const buffer = await response.arrayBuffer()
    try {
      return parseWavMono16(buffer) // known 16 kHz mono s16le from the pipeline
    } catch {
      // unexpected container: decode via WebAudio at 16 kHz instead
      const AudioContextCtor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!AudioContextCtor) throw new Error('no audio decoding available')
      const context = new AudioContextCtor({ sampleRate: 16000 })
      try {
        const decoded = await context.decodeAudioData(buffer)
        return decoded.getChannelData(0).slice()
      } finally {
        void context.close()
      }
    }
  })()

  samplesCache.set(url, pending)
  pending.catch(() => samplesCache.delete(url)) // failed loads are retryable
  return pending
}

export function useWaveform(audioUrl: string | undefined) {
  const [status, setStatus] = useState<WaveformStatus>('loading')
  const [peaks, setPeaks] = useState<WaveformPeaks | null>(null)

  useEffect(() => {
    if (!audioUrl) {
      setStatus('unavailable')
      setPeaks(null)
      return
    }
    const controller = new AbortController()
    let cancelled = false
    setStatus('loading')
    setPeaks(null)

    loadSamples(audioUrl, controller.signal)
      .then((samples) => {
        if (cancelled) return
        setPeaks(computePeaks(samples, PEAK_BUCKETS))
        setStatus('ready')
      })
      .catch(() => {
        if (cancelled) return
        setStatus('unavailable')
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [audioUrl])

  return { status, peaks }
}
