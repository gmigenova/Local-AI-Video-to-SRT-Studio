// Job result view: video preview + synchronized subtitle list + exports.
// Phase 4 upgrades this into the full editing experience (§11.5).

import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Download, FileJson, FileText, FileVideo2, Pencil } from 'lucide-react'

import { exportUrl } from '../../api/client'
import { useJob, useMediaItem, useSubtitles } from '../../api/hooks'
import VideoPlayer from '../../components/VideoPlayer'
import { Badge, Button, Card, CardHeader, StatusBadge } from '../../components/ui'
import { formatTimestamp, languageName } from '../../utils/format'
import type { Subtitle } from '../../types'

export default function JobResultPage() {
  const { jobId } = useParams()
  const job = useJob(jobId)
  const media = useMediaItem(job.data?.media_id)
  const subtitles = useSubtitles(jobId, job.data?.status === 'completed')
  const playerRef = useRef<HTMLDivElement>(null)
  const [activeId, setActiveId] = useState<string | null>(null)

  const seek = (subtitle: Subtitle) => {
    const video = playerRef.current?.querySelector('video')
    if (video) {
      video.currentTime = subtitle.start_ms / 1000 + 0.01
      video.play().catch(() => undefined)
    }
  }

  if (job.isLoading || !job.data) {
    return <p className="text-sm text-muted">Loading…</p>
  }
  if (job.data.status !== 'completed') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted">
          This job is not completed yet (status: {job.data.status}).
        </p>
        <Link to={`/jobs/${jobId}/processing`}>
          <Button variant="secondary">Open processing view</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/projects"
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft size={18} />
          </Link>
          <div>
            <h1 className="text-xl font-semibold">
              {media.data?.original_name ?? 'Result'}
            </h1>
            <div className="mt-1 flex items-center gap-2 text-xs text-muted">
              <StatusBadge status={job.data.status} />
              <span>
                {job.data.model_name} ·{' '}
                {languageName(job.data.detected_language ?? job.data.language)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <a href={exportUrl(jobId!, 'srt')} download>
            <Button>
              <Download size={15} /> SRT
            </Button>
          </a>
          {(
            [
              ['vtt', FileVideo2],
              ['txt', FileText],
              ['json', FileJson],
            ] as const
          ).map(([fmt, Icon]) => (
            <a key={fmt} href={exportUrl(jobId!, fmt)} download>
              <Button variant="secondary" className="capitalize">
                <Icon size={15} /> {fmt}
              </Button>
            </a>
          ))}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
        <div ref={playerRef} className="space-y-4">
          {job.data.media_id ? (
            <VideoPlayer
              mediaId={job.data.media_id}
              subtitles={subtitles.data ?? []}
              onActiveChange={(sub) => setActiveId(sub?.id ?? null)}
            />
          ) : null}
          <div className="flex items-center justify-between rounded-lg border border-dashed border-line px-4 py-3 text-xs text-muted">
            <span className="flex items-center gap-2">
              <Pencil size={14} /> Subtitle editing arrives in Phase 4
            </span>
            <span>{subtitles.data?.length ?? 0} subtitles</span>
          </div>
        </div>

        <Card className="flex max-h-[70vh] flex-col">
          <CardHeader
            title="Subtitles"
            subtitle="Click a line to jump to that moment"
            action={<Badge tone="neutral">{subtitles.data?.length ?? 0}</Badge>}
          />
          <ul className="nice-scroll flex-1 divide-y divide-line overflow-y-auto">
            {(subtitles.data ?? []).map((subtitle) => (
              <li key={subtitle.id}>
                <button
                  onClick={() => seek(subtitle)}
                  className={`w-full px-4 py-3 text-left transition-colors ${
                    activeId === subtitle.id ? 'bg-accent/10' : 'hover:bg-surface-2/50'
                  }`}
                >
                  <p className="font-mono text-[11px] text-muted">
                    {formatTimestamp(subtitle.start_ms)} → {formatTimestamp(subtitle.end_ms)}
                  </p>
                  <p className="mt-1 whitespace-pre-line text-sm">
                    {subtitle.text}
                    {subtitle.is_edited ? (
                      <span className="ml-2 align-middle">
                        <Badge tone="info">edited</Badge>
                      </span>
                    ) : null}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
