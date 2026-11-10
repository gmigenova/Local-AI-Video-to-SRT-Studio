// Upload page (§11.2): drag & drop, progress, metadata preview,
// audio stream selection, multiple files, validation feedback.

import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, XCircle } from 'lucide-react'

import { useMediaStreams, useSelectAudioStream, useUpload } from '../../api/hooks'
import { ApiError } from '../../api/client'
import type { AudioStream } from '../../types'
import UploadDropzone from '../../components/UploadDropzone'
import { Badge, Button, Card, CardHeader, inputClass } from '../../components/ui'
import { formatDuration } from '../../utils/format'

interface UploadItem {
  id: string
  file: File
  progress: number
  status: 'uploading' | 'done' | 'error'
  mediaId?: string
  durationMs?: number | null
  streams?: AudioStream[]
  error?: string
}

export default function UploadPage() {
  const { projectId } = useParams()
  const upload = useUpload()
  const [items, setItems] = useState<UploadItem[]>([])

  const update = (id: string, patch: Partial<UploadItem>) =>
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)))

  const handleFiles = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const item: UploadItem = {
          id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          file,
          progress: 0,
          status: 'uploading',
        }
        setItems((prev) => [...prev, item])
        upload.mutate(
          {
            file,
            projectId: projectId!,
            onProgress: (fraction) => update(item.id, { progress: fraction * 100 }),
          },
          {
            onSuccess: (result) =>
              update(item.id, {
                status: 'done',
                progress: 100,
                mediaId: result.media_id,
                durationMs: result.duration_ms,
                streams: result.audio_streams,
              }),
            onError: (error) =>
              update(item.id, {
                status: 'error',
                error: error instanceof ApiError ? error.message : 'Upload failed',
              }),
          },
        )
      }
    },
    [projectId, upload],
  )

  const allDone = items.length > 0 && items.every((i) => i.status === 'done')
  const anyUploading = items.some((i) => i.status === 'uploading')

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link
          to={`/projects/${projectId}`}
          className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text"
        >
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold">Upload videos</h1>
          <p className="mt-0.5 text-sm text-muted">
            Files are validated with FFprobe and stored locally.
          </p>
        </div>
      </div>

      <UploadDropzone onFiles={handleFiles} disabled={anyUploading} />

      {items.length > 0 ? (
        <Card>
          <CardHeader
            title={`Files (${items.filter((i) => i.status === 'done').length}/${items.length} uploaded)`}
            action={
              allDone ? (
                <Link to={`/projects/${projectId}`}>
                  <Button>Back to project</Button>
                </Link>
              ) : null
            }
          />
          <ul className="divide-y divide-line">
            {items.map((item) => (
              <li key={item.id} className="px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{item.file.name}</p>
                    <p className="mt-0.5 text-xs text-muted">
                      {item.status === 'done'
                        ? `${formatDuration(item.durationMs)} · uploaded & validated`
                        : item.status === 'error'
                          ? item.error
                          : `${Math.round(item.progress)}%`}
                    </p>
                  </div>
                  {item.status === 'done' ? (
                    <CheckCircle2 size={18} className="text-success" />
                  ) : item.status === 'error' ? (
                    <XCircle size={18} className="text-danger" />
                  ) : (
                    <Badge tone="info">{Math.round(item.progress)}%</Badge>
                  )}
                </div>

                {item.status === 'done' && item.mediaId ? (
                  <StreamSelector mediaId={item.mediaId} streams={item.streams ?? []} />
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}

function StreamSelector({ mediaId, streams }: { mediaId: string; streams: AudioStream[] }) {
  const select = useSelectAudioStream()
  const streamsQuery = useMediaStreams(mediaId)

  // single stream: nothing to choose
  if (streams.length <= 1) return null

  const current = streamsQuery.data ?? streams

  return (
    <div className="mt-3 flex items-center gap-3 rounded-lg border border-line bg-surface-2/40 px-3 py-2.5">
      <span className="text-xs font-medium text-muted">Audio track</span>
      <select
        className={inputClass}
        disabled={select.isPending}
        onChange={(e) =>
          select.mutate({ mediaId, streamIndex: Number(e.target.value) })
        }
        defaultValue={current[0]?.stream_index ?? 0}
      >
        {current.map((s) => (
          <option key={s.stream_index} value={s.stream_index}>
            Track #{s.stream_index} — {s.codec_name}
            {s.channels ? ` ${s.channels}ch` : ''}
            {s.language ? ` (${s.language})` : ''}
          </option>
        ))}
      </select>
      {select.isPending ? <Badge tone="info">saving…</Badge> : null}
    </div>
  )
}
