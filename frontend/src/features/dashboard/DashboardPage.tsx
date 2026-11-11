// Dashboard (§11.1): totals, job stats, recent activity, quick actions.

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  CheckCircle2,
  Clapperboard,
  Cpu,
  FolderOpen,
  Plus,
  Upload,
  XCircle,
} from 'lucide-react'

import { useCreateProject, useJobs, useProjects } from '../../api/hooks'
import { Button, Card, CardHeader, EmptyState, Field, Modal, inputClass, StatusBadge } from '../../components/ui'
import { languageName } from '../../utils/format'

export default function DashboardPage() {
  const projects = useProjects()
  const jobs = useJobs()
  const createProject = useCreateProject()
  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')

  const stats = useMemo(() => {
    const items = jobs.data?.items ?? []
    return {
      projects: projects.data?.length ?? 0,
      videos: new Set(items.flatMap((j) => j.media_id)).size,
      completed: items.filter((j) => j.status === 'completed').length,
      active: items.filter((j) => !['completed', 'failed', 'cancelled'].includes(j.status)).length,
      failed: items.filter((j) => j.status === 'failed').length,
      recent: items.slice(0, 8),
    }
  }, [projects.data, jobs.data])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-sm text-muted">
            Local AI video transcription — everything runs on this machine.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setShowNew(true)}>
            <Plus size={15} /> New project
          </Button>
          <Link to="/projects">
            <Button>
              <Upload size={15} /> Upload video
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatCard icon={<FolderOpen size={18} />} label="Projects" value={stats.projects} />
        <StatCard icon={<Clapperboard size={18} />} label="Videos" value={stats.videos} />
        <StatCard icon={<CheckCircle2 size={18} />} label="Completed" value={stats.completed} />
        <StatCard
          icon={stats.failed > 0 ? <XCircle size={18} /> : <Activity size={18} />}
          label={stats.failed > 0 ? `Failed / ${stats.active} active` : 'Active jobs'}
          value={stats.failed > 0 ? stats.failed : stats.active}
        />
      </div>

      <Card>
        <CardHeader title="Recent activity" subtitle="Latest transcription jobs" />
        {stats.recent.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Cpu size={28} />}
              title="No jobs yet"
              description="Create a project, upload a video and start your first transcription."
            />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {stats.recent.map((job) => (
              <li key={job.job_id}>
                <Link
                  to={
                    job.status === 'completed'
                      ? `/jobs/${job.job_id}`
                      : `/jobs/${job.job_id}/processing`
                  }
                  className="flex items-center justify-between gap-4 px-5 py-3 transition-colors hover:bg-surface-2/50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {job.model_name}
                      <span className="ml-2 text-xs font-normal text-muted">
                        {job.detected_language
                          ? languageName(job.detected_language)
                          : job.language
                            ? languageName(job.language)
                            : 'auto-detect'}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-muted">
                      {new Date(job.created_at).toLocaleString()}
                    </p>
                  </div>
                  <StatusBadge status={job.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal open={showNew} title="New project" onClose={() => setShowNew(false)}>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return
            await createProject.mutateAsync({ name: name.trim() })
            setName('')
            setShowNew(false)
          }}
        >
          <Field label="Project name">
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Course lectures"
              autoFocus
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setShowNew(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || createProject.isPending}>
              Create
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: number
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs text-muted">{label}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums sm:text-2xl">{value}</p>
        </div>
        <div className="shrink-0 rounded-lg bg-accent/10 p-2.5 text-accent">{icon}</div>
      </div>
    </Card>
  )
}
