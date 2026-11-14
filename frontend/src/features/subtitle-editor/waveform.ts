// Waveform decoding + peak computation (pure functions, unit-testable).
//
// The job audio endpoint serves the pipeline's extracted WAV — 16 kHz mono
// s16le PCM — so the primary path parses the RIFF container directly to
// Float32 samples. That avoids AudioContext.decodeAudioData, which would
// resample to the context rate and can blow memory on multi-hour videos.
// Anything unexpected throws and the caller falls back to decodeAudioData.

export interface WaveformPeaks {
  min: Float32Array
  max: Float32Array
}

/** Parse a RIFF/WAVE file (PCM s16le, any channel count) to mono floats.
 *  Multiple channels are averaged. Throws on non-PCM or malformed input. */
export function parseWavMono16(buffer: ArrayBuffer): Float32Array {
  const view = new DataView(buffer)
  const ascii = (offset: number, length: number) =>
    String.fromCharCode(...new Uint8Array(buffer, offset, length))

  if (buffer.byteLength < 44 || ascii(0, 4) !== 'RIFF' || ascii(8, 4) !== 'WAVE') {
    throw new Error('Not a RIFF/WAVE file')
  }

  let channels = 1
  let dataOffset = -1
  let dataLength = 0
  // walk chunks after "WAVE" (fmt may be followed by LIST etc. before data)
  let offset = 12
  while (offset + 8 <= buffer.byteLength) {
    const chunkId = ascii(offset, 4)
    const chunkSize = view.getUint32(offset + 4, true)
    if (chunkId === 'fmt ') {
      const audioFormat = view.getUint16(offset + 8, true)
      if (audioFormat !== 1) {
        throw new Error(`Unsupported WAV audio format: ${audioFormat}`)
      }
      channels = view.getUint16(offset + 10, true) || 1
    } else if (chunkId === 'data') {
      dataOffset = offset + 8
      dataLength = Math.min(chunkSize, buffer.byteLength - dataOffset)
    }
    offset += 8 + chunkSize + (chunkSize % 2) // chunks are word-aligned
  }
  if (dataOffset < 0 || dataLength < 2) {
    throw new Error('WAV file has no data chunk')
  }

  const frameCount = Math.floor(dataLength / 2 / channels)
  const samples = new Float32Array(frameCount)
  for (let i = 0; i < frameCount; i++) {
    let sum = 0
    for (let ch = 0; ch < channels; ch++) {
      sum += view.getInt16(dataOffset + (i * channels + ch) * 2, true) / 32768
    }
    samples[i] = sum / channels
  }
  return samples
}

/** Min/max envelope per bucket (a proper audio-wave look, not RMS). */
export function computePeaks(samples: Float32Array, buckets: number): WaveformPeaks {
  const count = Math.max(1, Math.min(buckets, Math.max(1, samples.length)))
  const min = new Float32Array(count)
  const max = new Float32Array(count)
  if (samples.length === 0) return { min, max }

  const step = samples.length / count
  for (let b = 0; b < count; b++) {
    const start = Math.floor(b * step)
    const end = Math.min(samples.length, Math.max(start + 1, Math.floor((b + 1) * step)))
    let lo = Infinity
    let hi = -Infinity
    for (let i = start; i < end; i++) {
      const value = samples[i]
      if (value < lo) lo = value
      if (value > hi) hi = value
    }
    min[b] = lo
    max[b] = hi
  }
  return { min, max }
}
