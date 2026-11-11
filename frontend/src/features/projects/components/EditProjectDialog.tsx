// Edit project: rename + edit description (PATCH /projects/{id}).

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { useUpdateProject } from '../../../api/hooks'
import type { Project } from '../../../types'
import { Button, Field, Modal, Spinner, inputClass } from '../../../components/ui'

export default function EditProjectDialog({
  project,
  onClose,
}: {
  project: Project
  onClose: () => void
}) {
  const updateProject = useUpdateProject()
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')

  // reset the form if a different project is opened
  useEffect(() => {
    setName(project.name)
    setDescription(project.description ?? '')
  }, [project])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      await updateProject.mutateAsync({
        id: project.id,
        name: trimmed,
        description: description.trim() || '',
      })
      onClose()
    } catch {
      /* error banner below shows updateProject.error */
    }
  }

  return (
    <Modal open title="Edit project" onClose={updateProject.isPending ? () => undefined : onClose}>
      <form className="space-y-4" onSubmit={(e) => void submit(e)}>
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

        {updateProject.isError ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
          >
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1 break-words">
              {updateProject.error instanceof Error
                ? updateProject.error.message
                : 'Could not save the project.'}
            </span>
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={updateProject.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={!name.trim() || updateProject.isPending}>
            {updateProject.isPending ? <Spinner className="h-4 w-4" /> : null}
            Save changes
          </Button>
        </div>
      </form>
    </Modal>
  )
}
