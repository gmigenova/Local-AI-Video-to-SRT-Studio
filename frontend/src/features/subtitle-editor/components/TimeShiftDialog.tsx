// Shift subtitle times globally: when the whole track (or everything from
// some point on) runs early/late against the audio, this nudges many rows
// at once as ONE undo step (auto-save persists it like any other edit).

import { useState } from 'react'
import { MoveHorizontal } from 'lucide-react'

import { Button, Modal, inputClass } from '../../../components/ui'

const QUICK_CHIPS = [-1000, -100, 100, 1000]

interface TimeShiftDialogProps {
  /** Key of the currently selected row (null = nothing selected). */
  selectedKey: string | null
  /** Index of the selected row, -1 when nothing is selected. */
  selectedIndex: number
  /** Total number of subtitle rows. */
  total: number
  onApply: (fromKey: string | null, deltaMs: number) => void
  onClose: () => void
}

export default function TimeShiftDialog({
  selectedKey,
  selectedIndex,
  total,
  onApply,
  onClose,
}: TimeShiftDialogProps) {
  const [deltaText, setDeltaText] = useState('')
  const [fromSelected, setFromSelected] = useState(false)

  const delta = Number.parseInt(deltaText, 10)
  const valid = Number.isNaN(delta) === false && delta !== 0
  const canShiftFromSelected = selectedKey !== null && selectedIndex >= 0
  const affected =
    !fromSelected || !canShiftFromSelected ? total : total - selectedIndex

  return (
    <Modal open title="Shift subtitle times" onClose={onClose}>
      <div className="space-y-4">
        <p className="flex items-center gap-2 text-xs text-muted">
          <MoveHorizontal size={14} className="shrink-0" />
          Move subtitle times by a fixed offset — one undo step, auto-saved.
        </p>

        <div className="flex items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-muted">
              Offset (ms)
            </span>
            <input
              className={`${inputClass} w-32 font-mono`}
              value={deltaText}
              placeholder="e.g. 500 or -250"
              inputMode="numeric"
              autoFocus
              onChange={(e) => setDeltaText(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-1.5 pb-0.5">
            {QUICK_CHIPS.map((ms) => (
              <Button
                key={ms}
                variant="secondary"
                className="px-2 py-1 text-xs font-mono"
                onClick={() => setDeltaText(String(ms))}
              >
                {ms > 0 ? `+${ms}` : ms}
              </Button>
            ))}
          </div>
        </div>

        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-[11px] font-medium text-muted">Scope</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="shift-scope"
              checked={!fromSelected}
              onChange={() => setFromSelected(false)}
            />
            All subtitles ({total})
          </label>
          <label
            className={`flex items-center gap-2 text-sm ${
              canShiftFromSelected ? '' : 'cursor-not-allowed opacity-50'
            }`}
          >
            <input
              type="radio"
              name="shift-scope"
              disabled={!canShiftFromSelected}
              checked={fromSelected}
              onChange={() => setFromSelected(true)}
            />
            From the selected subtitle to the end
            {canShiftFromSelected ? ` (${affected})` : ' (nothing selected)'}
          </label>
        </fieldset>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!valid || affected <= 0}
            onClick={() => {
              onApply(fromSelected && canShiftFromSelected ? selectedKey : null, delta)
              onClose()
            }}
          >
            <MoveHorizontal size={15} /> Shift {affected > 0 ? affected : ''} row
            {affected === 1 ? '' : 's'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
