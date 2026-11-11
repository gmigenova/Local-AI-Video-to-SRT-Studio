// Projects list (§11.1 actions: New Project, Open Project, Delete).

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, FolderOpen, Plus, Trash2 } from 'lucide-react'

import { useCreateProject, useProjects } from '../../api/hooks'
import type { Project } from '../../types'
import { Button, Card, EmptyState, Field, Modal, inputClass } from '../../components/ui'
import DeleteProjectDialog from './components/DeleteProjectDialog'

export default function ProjectsPage() {
  const projects = useProjects()
  const createProject = useCreateProject()
  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [deleting, setDeleting] = useState<Project | null>(null)

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-xl font-semibold">Projects</h1>
        <Button onClick={() => setShowNew(true)} className="self-start sm:self-auto">
          <Plus size={15} /> New project
        </Button>
      </div>

      {(projects.data ?? []).length === 0 && !projects.isLoading ? (
        <EmptyState
          icon={<FolderOpen size={28} />}
          title="No projects"
          description="Create your first project to start uploading videos."
          action={
            <Button onClick={() => setShowNew(true)}>
              <Plus size={15} /> New project
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(projects.data ?? []).map((project) => (
            <Link key={project.id} to={`/projects/${project.id}`}>
              <Card className="group p-5 transition-colors hover:border-accent/50">
                <div className="flex items-start justify-between">
                  <FolderOpen size={20} className="text-accent" />
                  <span className="flex items-center gap-1">
                    <button
                      title="Delete project"
                      aria-label={`Delete ${project.name}`}
                      className="rounded-md p-1.5 text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        setDeleting(project)
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                    <ChevronRight
                      size={16}
                      className="text-muted transition-transform group-hover:translate-x-0.5"
                    />
                  </span>
                </div>
                <p className="mt-3 truncate text-sm font-semibold">{project.name}</p>
                <p className="mt-1 line-clamp-2 min-h-[2rem] text-xs text-muted">
                  {project.description || 'No description'}
                </p>
                <p className="mt-2 text-[11px] text-muted/70">
                  Created {new Date(project.created_at).toLocaleDateString()}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {deleting ? (
        <DeleteProjectDialog project={deleting} onClose={() => setDeleting(null)} />
      ) : null}

      <Modal open={showNew} title="New project" onClose={() => setShowNew(false)}>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return
            await createProject.mutateAsync({
              name: name.trim(),
              description: description.trim() || undefined,
            })
            setName('')
            setDescription('')
            setShowNew(false)
          }}
        >
          <Field label="Project name">
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </Field>
          <Field label="Description (optional)">
            <textarea
              className={inputClass}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
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
