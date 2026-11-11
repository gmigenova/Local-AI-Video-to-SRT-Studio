// Delete-video confirmation: removes the upload plus every transcription
// job, subtitle export and hardsub render derived from it.

import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { useDeleteMedia } from '../../../api/hooks'
import type { MediaFile } from '../../../types'
import { Button, Modal, Spinner } from '../../../components/ui'

export default function DeleteMediaDialog({
  media,
  onClose,
}: {
  media: MediaFile
  onClose: () => void
}) {
  const deleteMedia = useDeleteMedia()
  const [error, setError] = useState<string | null>(null)

  const confirm = async () => {
    setError(null)
    try {
      await deleteMedia.mutateAsync({ mediaId: media.id, projectId: media.project_id })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <Modal open title="Delete video" onClose={deleteMedia.isPending ? () => undefined : onClose}>
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-3 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
          <div className="min-w-0">
            <p className="font-medium">
              Permanently delete{' '}
              <span className="break-words">“{media.original_name}”</span>?
            </p>
            <p className="mt-1 text-xs text-muted">This cannot be undone. It also removes:</p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-muted">
              <li>All transcription jobs for this video</li>
              <li>Saved subtitles &amp; raw transcripts</li>
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
          <Button variant="secondary" onClick={onClose} disabled={deleteMedia.isPending}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void confirm()} disabled={deleteMedia.isPending}>
            {deleteMedia.isPending ? <Spinner className="h-4 w-4" /> : null}
            Delete video
          </Button>
        </div>
      </div>
    </Modal>
  )
}
