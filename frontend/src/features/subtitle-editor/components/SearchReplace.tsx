// Search & replace across all subtitles (§11.5).

import { useState } from 'react'
import { Replace } from 'lucide-react'

import { Button, inputClass } from '../../../components/ui'

export default function SearchReplace({
  onReplaceAll,
  onClose,
}: {
  onReplaceAll: (search: string, replacement: string) => number
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [replacement, setReplacement] = useState('')
  const [result, setResult] = useState<string | null>(null)

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2/40 px-3 py-2.5 sm:px-4">
      <input
        className={`${inputClass} h-10 w-full py-1 sm:h-8 sm:w-44`}
        placeholder="Find"
        value={search}
        autoFocus
        onChange={(e) => {
          setSearch(e.target.value)
          setResult(null)
        }}
      />
      <input
        className={`${inputClass} h-10 w-full py-1 sm:h-8 sm:w-44`}
        placeholder="Replace with"
        value={replacement}
        onChange={(e) => {
          setReplacement(e.target.value)
          setResult(null)
        }}
      />
      <Button
        variant="secondary"
        className="h-8 px-2.5 py-1 text-xs"
        disabled={!search}
        onClick={() => {
          const count = onReplaceAll(search, replacement)
          setResult(count > 0 ? `Replaced in ${count} subtitle${count === 1 ? '' : 's'}` : 'No matches')
        }}
      >
        <Replace size={13} /> Replace all
      </Button>
      {result ? <span className="text-xs text-muted">{result}</span> : null}
      <div className="ml-auto">
        <Button variant="ghost" className="h-8 px-2 py-1 text-xs" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  )
}
