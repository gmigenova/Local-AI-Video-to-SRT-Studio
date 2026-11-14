// One subtitle in the editor list: compact row + expanded editing panel.

import { useEffect, useRef } from 'react'
import { AlertTriangle, Merge, Scissors, Trash2 } from 'lucide-react'

import { Badge, Button, inputClass } from '../../../components/ui'
import type { SubtitleIssue } from '../quality'
import { ISSUE_LABELS } from '../quality'
import type { EditorSubtitle } from '../useSubtitleEditor'
import { formatTimestamp } from '../../../utils/format'
import TimeInput from './TimeInput'

export default function SubtitleRow({
  sub,
  index,
  selected,
  active,
  issues,
  isLast,
  search,
  knownSpeakers,
  onSelect,
  onTextChange,
  onTimesChange,
  onSpeakerChange,
  onSplit,
  onMerge,
  onDelete,
}: {
  sub: EditorSubtitle
  index: number
  selected: boolean
  active: boolean
  issues: SubtitleIssue[]
  isLast: boolean
  search: string
  knownSpeakers: string[]
  onSelect: () => void
  onTextChange: (text: string) => void
  onTimesChange: (start: number, end: number) => void
  onSpeakerChange: (speaker: string | null) => void
  onSplit: () => void
  onMerge: () => void
  onDelete: () => void
}) {
  const textRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (selected) {
      // focus the text area when selecting with the keyboard
      const timer = window.setTimeout(() => {
        const el = textRef.current
        if (el && document.activeElement?.tagName !== 'INPUT') {
          el.focus({ preventScroll: true })
          el.setSelectionRange(el.value.length, el.value.length)
        }
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [selected])

  const startInvalid = sub.end_ms <= sub.start_ms

  // selection state is exclusive so the two tints never fight in the CSS:
  //   selected -> accent bar on the left edge + clear accent tint
  //   active  -> soft accent wash (the cue under the playhead)
  const rowTone = selected
    ? 'bg-accent/10 shadow-[inset_3px_0_0_0_var(--accent)]'
    : active
      ? 'bg-accent/5'
      : 'hover:bg-surface-2/40'

  return (
    <li
      id={`subtitle-row-${sub.key}`}
      className={`border-b border-line last:border-b-0 transition-colors ${rowTone}`}
    >
      {/* compact row: time line above, subtitle text below (full width) */}
      <button
        onClick={onSelect}
        className="flex w-full items-start gap-2.5 px-3 py-3 text-left sm:gap-3 sm:px-4 sm:py-3"
      >
        <span
          className={`w-5 shrink-0 pt-0.5 text-right font-mono text-[10px] tabular-nums sm:w-7 sm:text-xs ${
            selected ? 'font-semibold text-accent' : 'text-muted'
          }`}
        >
          {index + 1}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          {/* meta line: times left · flags right */}
          <span className="flex items-center gap-2 font-mono text-[10px] leading-none tabular-nums text-muted sm:text-xs">
            <span>{formatTimestamp(sub.start_ms)}</span>
            <span className="text-muted/50">→</span>
            <span>{formatTimestamp(sub.end_ms)}</span>
            {sub.speaker ? <Badge tone="info">{sub.speaker}</Badge> : null}
            <span className="ml-auto flex items-center gap-1.5 font-sans">
              {sub.is_edited ? <Badge tone="info">edited</Badge> : null}
              {issues.length > 0 ? (
                <span
                  title={issues.map((i) => ISSUE_LABELS[i.code] ?? i.code).join(', ')}
                  className="flex items-center"
                >
                  <AlertTriangle size={14} className="text-warning" />
                </span>
              ) : null}
            </span>
          </span>
          <span className="min-w-0 whitespace-pre-line text-base leading-normal">
            {search ? <Highlighted text={sub.text} search={search} /> : sub.text}
          </span>
        </span>
      </button>

      {/* expanded editor */}
      {selected ? (
        <div className="space-y-3 border-t border-line/60 bg-surface px-3 pb-4 pt-3 sm:px-4">
          <textarea
            ref={textRef}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-base leading-relaxed outline-none focus:border-accent"
            rows={Math.min(4, Math.max(2, sub.text.split('\n').length + 1))}
            value={sub.text}
            placeholder="Subtitle text…"
            onChange={(e) => onTextChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) e.currentTarget.blur()
            }}
          />

          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-end gap-2">
              <TimeInput
                label="Start (s)"
                valueMs={sub.start_ms}
                onCommit={(ms) => onTimesChange(ms, Math.max(ms + 1, sub.end_ms))}
              />
              <TimeInput
                label="End (s)"
                valueMs={sub.end_ms}
                invalid={startInvalid}
                onCommit={(ms) => onTimesChange(Math.min(sub.start_ms, ms - 1), ms)}
              />
              {/* speaker picker (diarization rows); empty = no label */}
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-muted">
                  Speaker
                </span>
                <select
                  className={`${inputClass} w-32 px-2 py-1.5 text-xs`}
                  value={sub.speaker ?? ''}
                  onChange={(e) => onSpeakerChange(e.target.value || null)}
                >
                  <option value="">—</option>
                  {knownSpeakers.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                  {sub.speaker && !knownSpeakers.includes(sub.speaker) ? (
                    <option value={sub.speaker}>{sub.speaker}</option>
                  ) : null}
                </select>
              </label>
            </div>

            <div className="flex flex-wrap gap-1.5">
              <Button variant="ghost" className="px-2 py-1.5 text-xs" onClick={onSplit} title="Split at playhead">
                <Scissors size={14} /> Split
              </Button>
              <Button
                variant="ghost"
                className="px-2 py-1.5 text-xs"
                onClick={onMerge}
                disabled={isLast}
                title="Merge with the next subtitle"
              >
                <Merge size={14} /> Merge next
              </Button>
              <Button
                variant="ghost"
                className="px-2 py-1.5 text-xs text-danger"
                onClick={onDelete}
                title="Delete this subtitle"
              >
                <Trash2 size={14} /> Delete
              </Button>
            </div>
          </div>

          {issues.length > 0 ? (
            <ul className="space-y-1 rounded-md bg-warning/5 px-3 py-2">
              {issues.map((issue, i) => (
                <li key={i} className="flex items-center gap-1.5 text-xs text-warning">
                  <AlertTriangle size={12} />
                  {issue.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

function Highlighted({ text, search }: { text: string; search: string }) {
  if (!search || !text.includes(search)) return <>{text}</>
  const parts = text.split(search)
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 ? (
            <mark className="rounded-sm bg-warning/30 text-inherit">{search}</mark>
          ) : null}
        </span>
      ))}
    </>
  )
}
