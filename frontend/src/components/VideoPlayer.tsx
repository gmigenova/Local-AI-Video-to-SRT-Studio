// Video player with subtitle overlay + time tracking (§11.5 basics).
// The full editing experience arrives in Phase 4.

import { useEffect, useRef, useState } from 'react'

import type { Subtitle } from '../types'
import { mediaStreamUrl } from '../api/client'
import { formatTimestamp } from '../utils/format'

export default function VideoPlayer({
  mediaId,
  subtitles,
  onActiveChange,
}: {
  mediaId: string
  subtitles: Subtitle[]
  onActiveChange?: (subtitle: Subtitle | null) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [currentMs, setCurrentMs] = useState(0)

  // find active subtitle on every time update
  useEffect(() => {
    const active =
      subtitles.find((s) => currentMs >= s.start_ms && currentMs < s.end_ms) ?? null
    onActiveChange?.(active)
  }, [currentMs, subtitles, onActiveChange])

  const activeText = subtitles.find(
    (s) => currentMs >= s.start_ms && currentMs < s.end_ms,
  )

  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-black">
      <video
        ref={videoRef}
        src={mediaStreamUrl(mediaId)}
        controls
        className="aspect-video w-full"
        onTimeUpdate={(e) => setCurrentMs(e.currentTarget.currentTime * 1000)}
      >
        Your browser does not support HTML5 video.
      </video>

      {activeText ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-14 flex justify-center px-6">
          <p className="whitespace-pre-line rounded bg-black/70 px-3 py-1.5 text-center text-sm text-white">
            {activeText.text}
          </p>
        </div>
      ) : null}

      <div className="absolute right-2 top-2 rounded bg-black/60 px-2 py-0.5 font-mono text-[11px] text-white/90">
        {formatTimestamp(currentMs)}
      </div>
    </div>
  )
}

/** seek the player from outside (click a subtitle -> jump) */
export function seekTo(videoWrapper: HTMLElement | null, seconds: number): void {
  const video = videoWrapper?.querySelector('video')
  if (video) video.currentTime = Math.max(0, seconds)
}
