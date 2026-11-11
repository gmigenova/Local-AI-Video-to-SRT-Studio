// Timeline strip: subtitle blocks along the media duration (§11.5 layout).
// Block height stacks overlapping subtitles, so overlaps are visible.

import type { EditorSubtitle } from '../useSubtitleEditor'

export default function Timeline({
  durationMs,
  currentMs,
  subtitles,
  activeKey,
  selectedKey,
  onSeek,
  onSelect,
}: {
  durationMs: number
  currentMs: number
  subtitles: EditorSubtitle[]
  activeKey: string | null
  selectedKey: string | null
  onSeek: (ms: number) => void
  onSelect: (key: string) => void
}) {
  const total = Math.max(durationMs, subtitles.at(-1)?.end_ms ?? 1, 1)

  const handleSeek = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - rect.left) / rect.width
    onSeek(Math.max(0, Math.min(1, ratio)) * total)
  }

  return (
    <div>
      <div
        className="relative h-12 cursor-crosshair touch-none overflow-hidden rounded-lg border border-line bg-surface-2 sm:h-10"
        onClick={handleSeek}
      >
        {subtitles.map((sub) => {
          const left = (sub.start_ms / total) * 100
          const width = Math.max(((sub.end_ms - sub.start_ms) / total) * 100, 0.25)
          const isActive = sub.key === activeKey
          const isSelected = sub.key === selectedKey
          return (
            <button
              key={sub.key}
              title={sub.text || '(empty)'}
              onClick={(e) => {
                e.stopPropagation()
                onSelect(sub.key)
                onSeek(sub.start_ms + 10)
              }}
              className={`absolute top-1 h-10 rounded-sm transition-colors sm:h-8 ${
                isSelected
                  ? 'bg-accent ring-1 ring-accent'
                  : isActive
                    ? 'bg-accent/60'
                    : 'bg-accent/25 hover:bg-accent/45'
              }`}
              style={{ left: `${left}%`, width: `${width}%` }}
            />
          )
        })}

        {/* playhead */}
        <div
          className="pointer-events-none absolute inset-y-0 w-px bg-danger"
          style={{ left: `${(currentMs / total) * 100}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted">
        <span>0:00</span>
        <span>{formatShort(total)}</span>
      </div>
    </div>
  )
}

function formatShort(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}
