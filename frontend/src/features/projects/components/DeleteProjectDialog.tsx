// Delete-project confirmation: spells out everything that is removed
// (videos, transcripts, subtitles, hardsub renders) before the cascade.

import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { useDeleteProject } from '../../../api/hooks'
import type { Project } from '../../../types'
import { Button, Modal, Spinner } from '../../../components/ui'

export default function DeleteProjectDialog({
  project,
  onClose,
  onDeleted,
}: {
  project: Project
  onClose: () => void
  onDeleted?: () => void
}) {
  const deleteProject = useDeleteProject()
  const [error, setError] = useState<string | null>(null)

  const confirm = async () => {
    setError(null)
    try {
      await deleteProject.mutateAsync(project.id)
      onDeleted?.()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <Modal open title="Delete project" onClose={deleteProject.isPending ? () => undefined : onClose}>
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-3 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
          <div className="min-w-0">
            <p className="font-medium">
              Permanently delete <span className="break-words">“{project.name}”</span>?
            </p>
            <p className="mt-1 text-xs text-muted">This cannot be undone. Everything in it goes:</p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-muted">
              <li>Uploaded videos (originals are deleted too)</li>
              <li>Transcription results, raw transcripts &amp; subtitles</li>
              <li>Hardsub render outputs</li>
            </ul>
          </div>
        </div>

        {error ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
          >
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1 break-words">{error}</span>
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={deleteProject.isPending}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void confirm()} disabled={deleteProject.isPending}>
            {deleteProject.isPending ? <Spinner className="h-4 w-4" /> : null}
            Delete project
          </Button>
        </div>
      </div>
    </Modal>
  )
}
