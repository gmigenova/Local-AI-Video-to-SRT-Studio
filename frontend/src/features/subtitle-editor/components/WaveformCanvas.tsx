// Canvas waveform layer for the editor timeline: min/max envelope bars in
// the accent colour, devicePixelRatio-aware, redrawn on resize. Renders
// nothing while loading/unavailable — the plain timeline background stays.

import { useEffect, useRef } from 'react'

import { useWaveform } from '../useWaveform'

export default function WaveformCanvas({ audioUrl }: { audioUrl: string }) {
  const { status, peaks } = useWaveform(audioUrl)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (status !== 'ready' || !peaks) return
    const canvas = canvasRef.current
    if (!canvas) return

    const draw = () => {
      const context = canvas.getContext('2d')
      if (!context) return
      const dpr = window.devicePixelRatio || 1
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      canvas.width = Math.max(1, Math.round(width * dpr))
      canvas.height = Math.max(1, Math.round(height * dpr))
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      context.clearRect(0, 0, width, height)

      // theme-aware stroke: the canvas inherits `color` from its class
      context.strokeStyle = getComputedStyle(canvas).color
      context.lineWidth = 1
      context.beginPath()
      const middle = height / 2
      const scale = height / 2
      for (let i = 0; i < peaks.min.length; i++) {
        const x = (i / peaks.min.length) * width
        const top = middle - Math.max(peaks.max[i], 0.004) * scale // always visible
        const bottom = middle - Math.min(peaks.min[i], -0.004) * scale
        context.moveTo(x, top)
        context.lineTo(x, bottom)
      }
      context.stroke()
    }

    draw()
    const observer = new ResizeObserver(() => draw())
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [status, peaks])

  if (status !== 'ready') return null
  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full text-accent opacity-50"
    />
  )
}
