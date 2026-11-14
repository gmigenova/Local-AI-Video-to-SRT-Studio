// Subtitle burn-in (hardsub) panel: re-encodes the original video with the
// subtitles permanently rendered into the picture, then download.
// Subtitle source: the current editor rows, or an external .srt file.
// Style: plain (SRT + optional font) or styled (ASS: font, size, colour,
// outline, vertical margin, position).

import { useState } from 'react'
import { Download, Film, X } from 'lucide-react'

import { renderDownloadUrl } from '../../../api/client'
import { useCancelRender, useRender, useStartRender } from '../../../api/hooks'
import { Badge, Button, Progress, Spinner, cn, inputClass } from '../../../components/ui'
import { ACTIVE_RENDER_STATUSES } from '../../../types'
import { formatBytes } from '../../../utils/format'

const FONT_SUGGESTIONS = ['Leelawadee UI', 'Tahoma', 'Arial']

interface Props {
  jobId: string
  /** Flush pending editor changes before rendering (auto-save is debounced). */
  onBeforeStart: () => Promise<boolean>
  onClose: () => void
}

/** Best-effort client-side cue count, for display only (backend re-validates). */
async function countCues(file: File): Promise<number | null> {
  try {
    const buffer = await file.arrayBuffer()
    let text: string
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(buffer)
    } catch {
      text = new TextDecoder('windows-874').decode(buffer)
    }
    const matches = text.match(/-->/g)
    return matches ? matches.length : 0
  } catch {
    return null
  }
}

export default function BurnInVideo({ jobId, onBeforeStart, onClose }: Props) {
  const renderQuery = useRender(jobId)
  const startRender = useStartRender()
  const cancelRender = useCancelRender()
  const [useExternal, setUseExternal] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [cueCount, setCueCount] = useState<number | null>(null)
  const [styled, setStyled] = useState(false)
  const [fontName, setFontName] = useState('')
  const [fontSize, setFontSize] = useState('48')
  const [fontColor, setFontColor] = useState('#ffffff')
  const [outline, setOutline] = useState('2')
  const [marginV, setMarginV] = useState('40')
  const [position, setPosition] = useState<'bottom' | 'middle' | 'top'>('bottom')
  const [startError, setStartError] = useState<string | null>(null)

  const render = renderQuery.data
  const active = render != null && ACTIVE_RENDER_STATUSES.includes(render.status)
  const canStart = !useExternal || file !== null

  async function handleFileChosen(chosen: File | null) {
    setFile(chosen)
    setCueCount(null)
    if (chosen) setCueCount(await countCues(chosen))
  }

  async function handleStart() {
    setStartError(null)
    if (!useExternal || file) {
      const saved = await onBeforeStart()
      if (!saved) {
        setStartError('Could not save your changes — fix the save error and try again.')
        return
      }
    }
    try {
      await startRender.mutateAsync({
        jobId,
        fontName: !styled && fontName.trim() ? fontName.trim() : undefined,
        srtFile: useExternal ? file : null,
        subtitleFormat: styled && !useExternal ? 'ass' : 'srt',
        style:
          styled && !useExternal
            ? {
                font_name: fontName.trim() || undefined,
                font_size: fontSize ? Number.parseInt(fontSize, 10) : undefined,
                primary_color: fontColor.replace('#', ''),
                outline: outline ? Number.parseFloat(outline) : undefined,
                margin_v: marginV ? Number.parseInt(marginV, 10) : undefined,
                position,
              }
            : undefined,
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
              {render.source === 'external' ? 'External SRT · ' : 'Editor subtitles · '}
              {render.subtitle_format === 'ass' ? 'styled · ' : ''}
              {render.status === 'queued'
                ? 'waiting in queue…'
                : render.status === 'cancelling'
                  ? 'cancelling…'
                  : 'rendering video (H.264)…'}
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
          <Badge tone="success">
            Video ready ({formatBytes(render.file_size)})
            {render.source === 'external' ? ' · external SRT' : ''}
          </Badge>
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

          {/* subtitle source selector */}
          <div className="flex overflow-hidden rounded-lg border border-line text-xs">
            <button
              className={cn(
                'px-2.5 py-1.5',
                !useExternal ? 'bg-primary text-primary-foreground' : 'text-muted',
              )}
              onClick={() => setUseExternal(false)}
            >
              Editor subtitles
            </button>
            <button
              className={cn(
                'px-2.5 py-1.5',
                useExternal ? 'bg-primary text-primary-foreground' : 'text-muted',
              )}
              onClick={() => setUseExternal(true)}
            >
              External .srt file
            </button>
          </div>

          {useExternal ? (
            <div className="flex flex-col gap-1 text-xs">
              <div className="flex items-center gap-2">
                <input
                  type="file"
                  accept=".srt"
                  className="text-xs"
                  onChange={(e) => void handleFileChosen(e.target.files?.[0] ?? null)}
                />
                {file ? (
                  <span className="text-muted">
                    {cueCount === null ? file.name : `${file.name} · ${cueCount} cues`}
                  </span>
                ) : (
                  <span className="text-muted">Choose a .srt file</span>
                )}
              </div>
              <span className="text-muted">
                Tip: use “Import SRT” in the toolbar to preview & edit it in the
                editor first.
              </span>
            </div>
          ) : null}

          {/* subtitle style selector (editor subtitles only) */}
          <div
            className="flex overflow-hidden rounded-lg border border-line text-xs"
            title={useExternal ? 'External .srt files burn with their own text' : undefined}
          >
            <button
              className={cn(
                'px-2.5 py-1.5',
                !styled ? 'bg-primary text-primary-foreground' : 'text-muted',
              )}
              onClick={() => setStyled(false)}
              disabled={useExternal}
            >
              Simple (SRT)
            </button>
            <button
              className={cn(
                'px-2.5 py-1.5',
                styled ? 'bg-primary text-primary-foreground' : 'text-muted',
              )}
              onClick={() => setStyled(true)}
              disabled={useExternal}
            >
              Styled (ASS)
            </button>
          </div>

          <input
            className={`${inputClass} w-44`}
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

          {styled && !useExternal ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <label className="flex items-center gap-1">
                Size
                <input
                  className={`${inputClass} w-16 px-2 py-1`}
                  type="number"
                  min={8}
                  max={200}
                  value={fontSize}
                  onChange={(e) => setFontSize(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-1">
                Colour
                <input
                  className="h-7 w-9 cursor-pointer rounded border border-line bg-transparent"
                  type="color"
                  value={fontColor}
                  onChange={(e) => setFontColor(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-1">
                Outline
                <input
                  className={`${inputClass} w-14 px-2 py-1`}
                  type="number"
                  min={0}
                  max={6}
                  step={0.5}
                  value={outline}
                  onChange={(e) => setOutline(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-1">
                Margin
                <input
                  className={`${inputClass} w-16 px-2 py-1`}
                  type="number"
                  min={0}
                  max={400}
                  value={marginV}
                  onChange={(e) => setMarginV(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-1">
                Position
                <select
                  className={`${inputClass} px-2 py-1`}
                  value={position}
                  onChange={(e) => setPosition(e.target.value as 'bottom' | 'middle' | 'top')}
                >
                  <option value="bottom">Bottom</option>
                  <option value="middle">Middle</option>
                  <option value="top">Top</option>
                </select>
              </label>
            </div>
          ) : null}

          <Button onClick={() => void handleStart()} disabled={startRender.isPending || !canStart}>
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
