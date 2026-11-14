// Rename speakers globally: diarization labels arrive as SPEAKER_00…, this
// dialog maps them to display names (one undo step, auto-save persists).

import { useMemo, useState } from 'react'
import { Users } from 'lucide-react'

import { Button, Modal, inputClass } from '../../../components/ui'

interface SpeakerRenameDialogProps {
  /** Distinct speakers currently present on the rows. */
  speakers: string[]
  /** Counts per speaker, for context. */
  counts: Record<string, number>
  onApply: (map: Record<string, string>) => void
  onClose: () => void
}

export default function SpeakerRenameDialog({
  speakers,
  counts,
  onApply,
  onClose,
}: SpeakerRenameDialogProps) {
  const initial = useMemo(
    () => Object.fromEntries(speakers.map((name) => [name, name])),
    [speakers],
  )
  const [draft, setDraft] = useState<Record<string, string>>(initial)

  return (
    <Modal open title="Rename speakers" onClose={onClose}>
      <div className="space-y-4">
        <p className="flex items-center gap-2 text-xs text-muted">
          <Users size={14} className="shrink-0" />
          Renaming applies to every subtitle of that speaker (one undo step).
        </p>

        <ul className="space-y-2">
          {speakers.map((speaker) => (
            <li key={speaker} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">
                {speaker}
                <span className="ml-1.5 font-sans text-muted/70">
                  · {counts[speaker] ?? 0} subtitle{(counts[speaker] ?? 0) === 1 ? '' : 's'}
                </span>
              </span>
              <span className="text-muted" aria-hidden>
                →
              </span>
              <input
                className={`${inputClass} w-40`}
                value={draft[speaker] ?? ''}
                placeholder="Display name"
                onChange={(e) => setDraft({ ...draft, [speaker]: e.target.value })}
              />
            </li>
          ))}
        </ul>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              onApply(draft)
              onClose()
            }}
          >
            <Users size={15} /> Rename
          </Button>
        </div>
      </div>
    </Modal>
  )
}
