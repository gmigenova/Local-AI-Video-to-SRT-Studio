// Time input: text field in seconds ("12.345"), parsed live.
// Invalid intermediate input ("1.", "abc") keeps the field editable without
// committing until it parses again.

import { useEffect, useState } from 'react'

import { msToInput, parseTimeInput } from '../time'
import { inputClass } from '../../../components/ui'

export default function TimeInput({
  valueMs,
  onCommit,
  label,
  invalid = false,
}: {
  valueMs: number
  onCommit: (ms: number) => void
  label: string
  invalid?: boolean
}) {
  const [text, setText] = useState(() => msToInput(valueMs))
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setText(msToInput(valueMs))
  }, [valueMs, focused])

  const parsed = parseTimeInput(text)

  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-muted">{label}</span>
      <input
        type="text"
        dir="ltr"
        className={`${inputClass} px-2 py-1.5 font-mono text-xs tabular-nums ${
          invalid ? 'border-danger' : ''
        }`}
        value={text}
        onFocus={(e) => {
          setFocused(true)
          e.target.select()
        }}
        onBlur={() => {
          setFocused(false)
          if (parsed !== null && parsed !== valueMs) onCommit(parsed)
          else setText(msToInput(valueMs))
        }}
        onChange={(e) => {
          setText(e.target.value)
          const next = parseTimeInput(e.target.value)
          if (next !== null && next !== valueMs) onCommit(next)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
        }}
      />
    </label>
  )
}
