// Processing screen (§11.4): stage, progress, elapsed, detected language,
// cancel. Polls job status every ~1.5s while active. Progress is reported
// honestly — stage-level values from the worker (§11.4 note).

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Cpu, RotateCcw, XCircle } from 'lucide-react'

import { useCancelJob, useJob, useMediaItem, useRetryJob } from '../../api/hooks'
import { Button, Card, Progress, StatusBadge } from '../../components/ui'
import { ACTIVE_JOB_STATUSES } from '../../types'
import { elapsedSince, languageName } from '../../utils/format'

export default function ProcessingPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const job = useJob(jobId)
  const media = useMediaItem(job.data?.media_id)
  const cancel = useCancelJob()
  const retry = useRetryJob()
  const [, setTick] = useState(0)

  // 1s ticker for the elapsed clock
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  // redirect to the result page when the job completes
  useEffect(() => {
    if (job.data?.status === 'completed') navigate(`/jobs/${jobId}`, { replace: true })
  }, [job.data?.status, jobId, navigate])

  if (job.isLoading || !job.data) {
    return <p className="text-sm text-muted">Loading job…</p>
  }

  const data = job.data
  const isActive = ACTIVE_JOB_STATUSES.includes(data.status)
  const failed = data.status === 'failed'

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <Link
          to="/projects"
          className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text"
        >
          <ArrowLeft size={18} />
        </Link>
        <h1 className="text-xl font-semibold">Processing</h1>
      </div>

      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">
              {media.data?.original_name ?? 'Video'}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={data.status} />
              <span className="text-xs text-muted">
                model {data.model_name}
                {data.detected_language
                  ? ` · detected ${languageName(data.detected_language)} (${Math.round(
                      (data.language_probability ?? 0) * 100,
                    )}%)`
                  : data.language
                    ? ` · ${languageName(data.language)}`
                    : ''}
              </span>
            </div>
          </div>
          <Cpu size={22} className="text-muted" />
        </div>

        <div className="mt-6 space-y-2">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>{data.current_stage ?? data.status.replace(/_/g, ' ')}</span>
            <span className="tabular-nums">{Math.round(data.progress)}%</span>
          </div>
          <Progress value={data.progress} />
        </div>

        <div className="mt-6 grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs text-muted">Elapsed</p>
            <p className="mt-1 font-mono tabular-nums">
              {data.started_at ? formatElapsed(data.started_at, isActive) : '—'}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Stage</p>
            <p className="mt-1">{data.current_stage ?? '—'}</p>
          </div>
        </div>

        {failed ? (
          <div className="mt-6 rounded-lg border border-danger/40 bg-danger/5 p-4">
            <p className="flex items-center gap-2 text-sm font-medium text-danger">
              <XCircle size={16} /> Transcription failed
            </p>
            <p className="mt-1.5 text-xs text-muted">
              {data.error_message ?? 'Unknown error'}
            </p>
            <div className="mt-3 flex gap-2">
              <Button
                variant="secondary"
                onClick={() => retry.mutate(data.job_id)}
                disabled={retry.isPending}
              >
                <RotateCcw size={14} /> Retry
              </Button>
            </div>
          </div>
        ) : data.status === 'cancelled' || data.status === 'cancelling' ? (
          <div className="mt-6 rounded-lg border border-warning/40 bg-warning/5 p-4">
            <p className="text-sm font-medium text-warning">
              {data.status === 'cancelling' ? 'Cancelling…' : 'Cancelled'}
            </p>
            {data.status === 'cancelled' ? (
              <div className="mt-3">
                <Button
                  variant="secondary"
                  onClick={() => retry.mutate(data.job_id)}
                  disabled={retry.isPending}
                >
                  <RotateCcw size={14} /> Retry
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {isActive && data.status !== 'cancelling' ? (
          <div className="mt-6 flex justify-end">
            <Button
              variant="danger"
              onClick={() => cancel.mutate(data.job_id)}
              disabled={cancel.isPending}
            >
              <XCircle size={15} /> Cancel
            </Button>
          </div>
        ) : null}
      </Card>
    </div>
  )
}

function formatElapsed(startedAt: string, running: boolean): string {
  const ms = running ? elapsedSince(startedAt) : 0
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
