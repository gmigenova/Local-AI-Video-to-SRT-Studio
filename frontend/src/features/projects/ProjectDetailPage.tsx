// Project detail: media library + start transcription + per-project jobs.

import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Clapperboard, Film, Sparkles, Trash2, Upload } from 'lucide-react'

import { useCreateJob, useJobs, useMedia, useProject } from '../../api/hooks'
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  Modal,
  StatusBadge,
} from '../../components/ui'
import TranscriptionSettingsForm from '../../components/TranscriptionSettingsForm'
import { useSettingsStore } from '../../stores/settings'
import { formatBytes, formatDuration, languageName } from '../../utils/format'
import type { MediaFile } from '../../types'
import DeleteProjectDialog from './components/DeleteProjectDialog'

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const project = useProject(projectId)
  const media = useMedia(projectId)
  const jobs = useJobs()
  const createJob = useCreateJob()
  const [settingsFor, setSettingsFor] = useState<MediaFile | null>(null)
  const [showDelete, setShowDelete] = useState(false)

  const mediaIds = useMemo(() => new Set((media.data ?? []).map((m) => m.id)), [media.data])
  const projectJobs = useMemo(
    () => (jobs.data?.items ?? []).filter((j) => mediaIds.has(j.media_id)),
    [jobs.data, mediaIds],
  )

  const startJob = async () => {
    if (!settingsFor) return
    const resolved = useSettingsStore.getState().resolved()
    const created = await createJob.mutateAsync({
      media_id: settingsFor.id,
      model: resolved.model,
      language: resolved.language,
      settings: resolved.settings,
    })
    setSettingsFor(null)
    navigate(`/jobs/${created.job_id}/processing`)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/projects"
            className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft size={18} />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold">{project.data?.name ?? '…'}</h1>
            {project.data?.description ? (
              <p className="mt-0.5 truncate text-sm text-muted">
                {project.data.description}
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          <Link to={`/projects/${projectId}/upload`}>
            <Button>
              <Upload size={15} /> Upload video
            </Button>
          </Link>
          {project.data ? (
            <Button
              variant="danger"
              title="Delete this project and everything in it"
              onClick={() => setShowDelete(true)}
            >
              <Trash2 size={15} /> Delete
            </Button>
          ) : null}
        </div>
      </div>

      <Card>
        <CardHeader
          title="Videos"
          subtitle="Files stored locally — originals are never modified"
        />
        {(media.data ?? []).length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Film size={28} />}
              title="No videos yet"
              description="Upload an MP4, MKV, AVI, MOV, WebM or M4V file to get started."
              action={
                <Link to={`/projects/${projectId}/upload`}>
                  <Button>
                    <Upload size={15} /> Upload video
                  </Button>
                </Link>
              }
            />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {(media.data ?? []).map((file) => {
              const lastJob = projectJobs.find((j) => j.media_id === file.id)
              return (
                <li
                  key={file.id}
                  className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <div className="shrink-0 rounded-lg bg-surface-2 p-2.5 text-muted">
                      <Clapperboard size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{file.original_name}</p>
                      <p className="mt-0.5 text-xs text-muted">
                        {formatDuration(file.duration_ms)} · {formatBytes(file.file_size)} ·{' '}
                        {file.video_codec ?? '?'} / {file.audio_codec ?? '?'}
                        {file.width ? ` · ${file.width}×${file.height}` : ''}
                      </p>
                    </div>
                    {lastJob ? (
                      <span className="sm:hidden">
                        <StatusBadge status={lastJob.status} />
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                    {lastJob ? (
                      <span className="hidden sm:inline">
                        <StatusBadge status={lastJob.status} />
                      </span>
                    ) : null}
                    {lastJob?.status === 'completed' ? (
                      <Link to={`/jobs/${lastJob.job_id}`}>
                        <Button variant="secondary">Open result</Button>
                      </Link>
                    ) : null}
                    <Button
                      onClick={() => setSettingsFor(file)}
                      disabled={createJob.isPending}
                    >
                      <Sparkles size={15} /> Transcribe
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      {projectJobs.length > 0 ? (
        <Card>
          <CardHeader title="Jobs" subtitle="Transcription runs for this project" />
          <ul className="divide-y divide-line">
            {projectJobs.map((job) => (
              <li key={job.job_id}>
                <Link
                  to={
                    job.status === 'completed'
                      ? `/jobs/${job.job_id}`
                      : `/jobs/${job.job_id}/processing`
                  }
                  className="flex items-center justify-between px-5 py-3 transition-colors hover:bg-surface-2/50"
                >
                  <div className="text-sm">
                    <span className="font-medium">{job.model_name}</span>
                    <span className="ml-2 text-xs text-muted">
                      {job.detected_language ? languageName(job.detected_language) : 'auto'}
                      {' · '}
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                  </div>
                  <StatusBadge status={job.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Modal
        open={settingsFor !== null}
        title={`Transcribe “${settingsFor?.original_name ?? ''}”`}
        onClose={() => setSettingsFor(null)}
      >
        <TranscriptionSettingsForm
          onSubmit={startJob}
          onCancel={() => setSettingsFor(null)}
          submitting={createJob.isPending}
        />
      </Modal>

      {showDelete && project.data ? (
        <DeleteProjectDialog
          project={project.data}
          onClose={() => setShowDelete(false)}
          onDeleted={() => navigate('/projects')}
        />
      ) : null}
    </div>
  )
}
