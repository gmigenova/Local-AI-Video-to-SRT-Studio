// One subtitle in the editor list: compact row + expanded editing panel.

import { useEffect, useRef } from 'react'
import { AlertTriangle, Merge, Scissors, Trash2 } from 'lucide-react'

import { Badge, Button } from '../../../components/ui'
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
  onSelect,
  onTextChange,
  onTimesChange,
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
  onSelect: () => void
  onTextChange: (text: string) => void
  onTimesChange: (start: number, end: number) => void
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

  return (
    <li
      id={`subtitle-row-${sub.key}`}
      className={`border-b border-line last:border-b-0 transition-colors ${
        active ? 'bg-accent/5' : ''
      } ${selected ? 'bg-surface-2/60' : 'hover:bg-surface-2/30'}`}
    >
      {/* compact row */}
      <button
        onClick={onSelect}
        className="flex w-full items-start gap-3 px-4 py-2.5 text-left"
      >
        <span className="w-7 shrink-0 pt-0.5 text-right font-mono text-[11px] tabular-nums text-muted">
          {index + 1}
        </span>
        <span className="w-36 shrink-0 pt-0.5 font-mono text-[11px] tabular-nums text-muted">
          {formatTimestamp(sub.start_ms)}
          <span className="mx-1 text-muted/50">→</span>
          {formatTimestamp(sub.end_ms)}
        </span>
        <span className="min-w-0 flex-1 whitespace-pre-line text-sm leading-snug">
          {search ? <Highlighted text={sub.text} search={search} /> : sub.text}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
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
      </button>

      {/* expanded editor */}
      {selected ? (
        <div className="space-y-3 border-t border-line/60 bg-surface px-4 pb-4 pt-3">
          <textarea
            ref={textRef}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm leading-relaxed outline-none focus:border-accent"
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
