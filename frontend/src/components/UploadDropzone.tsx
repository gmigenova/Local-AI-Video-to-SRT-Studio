// Drag-and-drop / click-to-browse file picker (§11.2).

import { useCallback, useRef, useState } from 'react'
import { FileVideo } from 'lucide-react'

import { cn } from './ui'

const ACCEPT = '.mp4,.mkv,.avi,.mov,.webm,.m4v'

export default function UploadDropzone({
  onFiles,
  disabled = false,
}: {
  onFiles: (files: File[]) => void
  disabled?: boolean
}) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      setDragging(false)
      if (disabled) return
      const files = Array.from(event.dataTransfer.files).filter((f) =>
        /\.(mp4|mkv|avi|mov|webm|m4v)$/i.test(f.name),
      )
      if (files.length) onFiles(files)
    },
    [disabled, onFiles],
  )

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 transition-colors',
        dragging
          ? 'border-accent bg-accent/5'
          : 'border-line hover:border-accent/50 hover:bg-surface-2/40',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      <FileVideo size={32} className="text-muted" />
      <div className="text-center">
        <p className="text-sm font-medium">Drag &amp; drop videos here</p>
        <p className="mt-1 text-xs text-muted">
          or click to browse — MP4, MKV, AVI, MOV, WebM, M4V
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) onFiles(files)
          e.target.value = ''
        }}
      />
    </div>
  )
}
