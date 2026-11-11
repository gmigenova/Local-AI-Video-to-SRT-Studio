// Subtitle burn-in (hardsub) panel: re-encodes the original video with the
// current subtitles permanently rendered into the picture, then download.

import { useState } from 'react'
import { Download, Film, X } from 'lucide-react'

import { renderDownloadUrl } from '../../../api/client'
import { useCancelRender, useRender, useStartRender } from '../../../api/hooks'
import { Badge, Button, Progress, Spinner, inputClass } from '../../../components/ui'
import { ACTIVE_RENDER_STATUSES } from '../../../types'
import { formatBytes } from '../../../utils/format'

const FONT_SUGGESTIONS = ['Leelawadee UI', 'Tahoma', 'Arial']

interface Props {
  jobId: string
  /** Flush pending editor changes before rendering (auto-save is debounced). */
  onBeforeStart: () => Promise<boolean>
  onClose: () => void
}

export default function BurnInVideo({ jobId, onBeforeStart, onClose }: Props) {
  const renderQuery = useRender(jobId)
  const startRender = useStartRender()
  const cancelRender = useCancelRender()
  const [fontName, setFontName] = useState('')
  const [startError, setStartError] = useState<string | null>(null)

  const render = renderQuery.data
  const active = render != null && ACTIVE_RENDER_STATUSES.includes(render.status)

  async function handleStart() {
    setStartError(null)
    const saved = await onBeforeStart()
    if (!saved) {
      setStartError('Could not save your changes — fix the save error and try again.')
      return
    }
    try {
      await startRender.mutateAsync({
        jobId,
        fontName: fontName.trim() || undefined,
      })
    } catch (error) {
      setStartError(error instanceof Error ? error.message : 'Could not start the render.')
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Film size={15} /> Burn subtitles into video
      </div>

      {active && render ? (
        <div className="flex min-w-56 flex-1 flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>
              {render.status === 'queued'
                ? 'Waiting in queue…'
                : render.status === 'cancelling'
                  ? 'Cancelling…'
                  : 'Rendering video (H.264)…'}
            </span>
            <span>{Math.round(render.progress)}%</span>
          </div>
          <Progress value={render.progress} />
          {render.status !== 'cancelling' ? (
            <Button
              variant="secondary"
              className="self-start px-2 py-1 text-xs"
              onClick={() =>
                cancelRender.mutate({ renderId: render.render_id, jobId })
              }
            >
              Cancel render
            </Button>
          ) : null}
        </div>
      ) : render?.status === 'completed' ? (
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <Badge tone="success">Video ready ({formatBytes(render.file_size)})</Badge>
          <a href={renderDownloadUrl(render.render_id)} download>
            <Button>
              <Download size={15} /> Download video
            </Button>
          </a>
          <Button variant="secondary" onClick={() => void handleStart()} disabled={startRender.isPending}>
            {startRender.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
            Render again
          </Button>
        </div>
      ) : (
        <div className="flex flex-1 flex-wrap items-center gap-2">
          {render?.status === 'failed' ? (
            <Badge tone="danger">{render.error_message ?? 'Render failed'}</Badge>
          ) : null}
          {render?.status === 'cancelled' ? <Badge tone="info">Cancelled</Badge> : null}
          <input
            className={`${inputClass} w-48`}
            list="burn-font-suggestions"
            placeholder="Font (optional, e.g. Thai font)"
            value={fontName}
            onChange={(e) => setFontName(e.target.value)}
          />
          <datalist id="burn-font-suggestions">
            {FONT_SUGGESTIONS.map((font) => (
              <option key={font} value={font} />
            ))}
          </datalist>
          <Button onClick={() => void handleStart()} disabled={startRender.isPending}>
            {startRender.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Film size={15} />}
            {render ? 'Try again' : 'Render video'}
          </Button>
        </div>
      )}

      {startError ? <p className="w-full text-xs text-danger">{startError}</p> : null}

      <button
        className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-text"
        onClick={onClose}
        title="Close"
      >
        <X size={16} />
      </button>
    </div>
  )
}
