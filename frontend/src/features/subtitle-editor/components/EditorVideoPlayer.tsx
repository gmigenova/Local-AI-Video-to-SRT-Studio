// Editor video player with live subtitle overlay (§11.5).
// Updates the overlay in real time as the user edits (working copy passed in).

import type { RefObject } from 'react'

import { mediaStreamUrl } from '../../../api/client'
import type { EditorSubtitle } from '../useSubtitleEditor'

export default function EditorVideoPlayer({
  mediaId,
  subtitles,
  currentMs,
  videoRef,
  onTimeUpdate,
  onDurationChange,
}: {
  mediaId: string
  subtitles: EditorSubtitle[]
  currentMs: number
  videoRef: RefObject<HTMLVideoElement>
  onTimeUpdate: (ms: number) => void
  onDurationChange: (ms: number) => void
}) {
  const active = subtitles.find((s) => currentMs >= s.start_ms && currentMs < s.end_ms)

  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-black">
      <video
        ref={videoRef}
        src={mediaStreamUrl(mediaId)}
        controls
        className="aspect-video w-full"
        onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime * 1000)}
        onLoadedMetadata={(e) => onDurationChange(e.currentTarget.duration * 1000)}
      >
        Your browser does not support HTML5 video.
      </video>

      {active ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-14 flex justify-center px-6">
          <p className="whitespace-pre-line rounded bg-black/70 px-4 py-2 text-center text-lg leading-snug text-white">
            {active.text || ' '}
          </p>
        </div>
      ) : null}
    </div>
  )
}
