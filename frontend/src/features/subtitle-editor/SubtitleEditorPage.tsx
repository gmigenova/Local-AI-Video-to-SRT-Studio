// Subtitle editor (§11.5) — the main workspace:
// video + timeline left, editable subtitle list right, auto-save throughout.
// Shortcuts: Space play/pause · Ctrl+S save · ↑/↓ navigate · Delete remove ·
// Ctrl+Z / Ctrl+Y undo/redo.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  Captions,
  CheckCircle2,
  Download,
  FileText,
  FileUp,
  Film,
  Languages,
  Plus,
  Redo2,
  RefreshCw,
  Search,
  Type,
  Undo2,
  X,
} from 'lucide-react'

import { exportUrl } from '../../api/client'
import { useJob, useMediaItem, useSubtitles } from '../../api/hooks'
import { api } from '../../api/client'
import {
  Badge,
  Button,
  Card,
  DropdownItem,
  DropdownMenu,
  Spinner,
  StatusBadge,
  cn,
} from '../../components/ui'
import BurnInVideo from './components/BurnInVideo'
import EditorVideoPlayer from './components/EditorVideoPlayer'
import Timeline from './components/Timeline'
import SubtitleRow from './components/SubtitleRow'
import SearchReplace from './components/SearchReplace'
import TranslateDialog from './components/TranslateDialog'
import { checkSubtitles, ISSUE_LABELS } from './quality'
import { useSubtitleEditor } from './useSubtitleEditor'
import { languageName } from '../../utils/format'

export default function SubtitleEditorPage() {
  const { jobId } = useParams()
  const queryClient = useQueryClient()
  const job = useJob(jobId)
  const completed = job.data?.status === 'completed'
  const media = useMediaItem(job.data?.media_id)
  const subtitlesQuery = useSubtitles(jobId, completed)
  const editor = useSubtitleEditor(jobId)

  const videoRef = useRef<HTMLVideoElement>(null)
  const [currentMs, setCurrentMs] = useState(0)
  const [durationMs, setDurationMs] = useState(0)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [showSearch, setShowSearch] = useState(false)
  const [search, setSearch] = useState('')
  const [showWarnings, setShowWarnings] = useState(false)
  const [showRender, setShowRender] = useState(false)
  const [showTranslate, setShowTranslate] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const loadedToken = useRef(-1)
  const importInputRef = useRef<HTMLInputElement>(null)

  // Reprocess/import replace the server-side rows, then we reload. The
  // fresh list MUST land in the query cache BEFORE the reload token is
  // bumped: the working-copy effect keys off the token, so bumping it
  // while the cache still holds the previous data makes it accept the
  // stale rows — and the refetch that arrives later is then ignored.
  const reloadSubtitles = useCallback(async () => {
    if (!jobId) return
    const fresh = await api.listSubtitles(jobId)
    queryClient.setQueryData(['subtitles', jobId], fresh)
    setReloadToken((t) => t + 1)
  }, [jobId, queryClient])

  const handleImportFile = useCallback(
    async (file: File) => {
      if (!jobId) return
      setActionError(null)
      if (!file.name.toLowerCase().endsWith('.srt')) {
        setActionError('Expected a .srt file.')
        return
      }
      if (
        !window.confirm(
          'Importing replaces the current subtitle list with the file contents. Continue?',
        )
      ) {
        return
      }
      setImporting(true)
      try {
        // flush pending edits first so a debounced auto-save cannot
        // overwrite the imported rows afterwards
        await editor.save()
        await api.importSubtitles(jobId, file)
        await reloadSubtitles()
      } catch (error) {
        setActionError(error instanceof Error ? error.message : 'Import failed')
      } finally {
        setImporting(false)
      }
    },
    [jobId, editor, reloadSubtitles],
  )

  // initialize the working copy once (and after each reprocess)
  useEffect(() => {
    const data = subtitlesQuery.data
    if (!data || !jobId) return
    if (loadedToken.current === reloadToken) return
    loadedToken.current = reloadToken
    editor.accept(data)
    setSelectedKey(data[0]?.id ?? null)
  }, [subtitlesQuery.data, reloadToken, jobId, editor])

  // warn before leaving with unsaved changes
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (editor.dirty) e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [editor.dirty])

  const issues = useMemo(() => checkSubtitles(editor.subs), [editor.subs])
  const pendingChars = useMemo(
    () => editor.subs.reduce((n, s) => n + s.text.trim().length, 0),
    [editor.subs],
  )
  const totalIssues = useMemo(
    () => Array.from(issues.values()).reduce((n, list) => n + list.length, 0),
    [issues],
  )
  const activeKey =
    editor.subs.find((s) => currentMs >= s.start_ms && currentMs < s.end_ms)?.key ?? null
  const selectedIndex = editor.subs.findIndex((s) => s.key === selectedKey)

  const seek = useCallback((ms: number) => {
    const video = videoRef.current
    if (video) video.currentTime = ms / 1000
  }, [])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) void video.play()
    else video.pause()
  }, [])

  /** Bring a subtitle row into view in the list ('nearest' for small moves,
   *  'center' for jumps like a timeline click). */
  const scrollToRow = useCallback((key: string, block: ScrollLogicalPosition = 'nearest') => {
    document.getElementById(`subtitle-row-${key}`)?.scrollIntoView({
      behavior: 'smooth',
      block,
    })
  }, [])

  const selectIndex = useCallback(
    (index: number) => {
      if (index < 0 || index >= editor.subs.length) return
      const row = editor.subs[index]
      setSelectedKey(row.key)
      seek(row.start_ms + 10) // follow selection: video jumps to the cue
      scrollToRow(row.key)
    },
    [editor.subs, seek, scrollToRow],
  )

  /** Click on a subtitle row: select it and seek the video to its cue.
   *  Only when the selection CHANGES - re-clicking the already-selected row
   *  (e.g. to re-read its text) must not restart the video position. */
  const selectRow = useCallback(
    (key: string, startMs: number) => {
      if (key === selectedKey) return
      setSelectedKey(key)
      seek(startMs + 10)
    },
    [selectedKey, seek],
  )

  // global keyboard shortcuts (§11.5)
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      const typing =
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      const mod = event.ctrlKey || event.metaKey

      if (mod && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void editor.save()
        return
      }
      if (typing) return

      if (event.code === 'Space') {
        event.preventDefault()
        togglePlay()
      } else if (event.key === 'ArrowDown') {
        event.preventDefault()
        selectIndex(selectedIndex + 1)
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        selectIndex(selectedIndex - 1)
      } else if (event.key === 'Delete' && selectedKey) {
        event.preventDefault()
        editor.remove(selectedKey)
        selectIndex(Math.min(selectedIndex, editor.subs.length - 2))
      } else if (mod && !event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        editor.undo()
      } else if (
        (mod && event.key.toLowerCase() === 'y') ||
        (mod && event.shiftKey && event.key.toLowerCase() === 'z')
      ) {
        event.preventDefault()
        editor.redo()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [editor, selectedIndex, selectedKey, selectIndex, togglePlay])

  if (job.isLoading || !job.data) {
    return <p className="text-sm text-muted">Loading…</p>
  }
  if (!completed) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted">
          This job is not completed yet (status: {job.data.status}).
        </p>
        <Link to={`/jobs/${jobId}/processing`}>
          <Button variant="secondary">Open processing view</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* header: title + document-level actions (save state, export, hardsub) */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            to="/projects"
            aria-label="Back to projects"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft size={18} />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold leading-tight">
              {media.data?.original_name ?? 'Subtitles'}
            </h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
              <StatusBadge status={job.data.status} />
              <span className="min-w-0 truncate">
                {job.data.model_name} ·{' '}
                {languageName(job.data.detected_language ?? job.data.language)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <SaveIndicator
            dirty={editor.dirty}
            saving={editor.saving}
            savedAt={editor.savedAt}
            error={editor.saveError}
          />
          <DropdownMenu label={<><Download size={15} /> Export</>} title="Download subtitles">
            <DropdownItem
              icon={<FileText size={15} />}
              hint=".srt"
              href={exportUrl(jobId!, 'srt')}
              download
            >
              SubRip subtitles
            </DropdownItem>
            <DropdownItem
              icon={<Captions size={15} />}
              hint=".vtt"
              href={exportUrl(jobId!, 'vtt')}
              download
            >
              WebVTT subtitles
            </DropdownItem>
            <DropdownItem
              icon={<Type size={15} />}
              hint=".txt"
              href={exportUrl(jobId!, 'txt')}
              download
            >
              Plain text
            </DropdownItem>
            <DropdownItem
              icon={<Braces size={15} />}
              hint=".json"
              href={exportUrl(jobId!, 'json')}
              download
            >
              JSON data
            </DropdownItem>
          </DropdownMenu>
          <Button
            variant="secondary"
            onClick={() => setShowRender((v) => !v)}
            title="Burn subtitles into the video (hardsub)"
          >
            <Film size={15} /> Hardsub
          </Button>
        </div>
      </div>

      {/* toolbar: editing tools left · list-level actions right */}
      <div className="flex flex-wrap items-center justify-between gap-y-2">
        <div className="flex items-center gap-1.5">
          <Button
            variant="secondary"
            className="px-2.5"
            onClick={editor.undo}
            disabled={!editor.canUndo}
            title="Undo (Ctrl+Z)"
          >
            <Undo2 size={16} />
          </Button>
          <Button
            variant="secondary"
            className="px-2.5"
            onClick={editor.redo}
            disabled={!editor.canRedo}
            title="Redo (Ctrl+Y)"
          >
            <Redo2 size={16} />
          </Button>
          <ToolbarDivider />
          <Button
            variant="secondary"
            onClick={() => setShowSearch((v) => !v)}
            title="Search & replace"
          >
            <Search size={15} /> Find
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              const key = editor.addAfter(selectedKey)
              if (key) setSelectedKey(key)
            }}
            title="Add subtitle after the selected one"
          >
            <Plus size={15} /> Add
          </Button>
        </div>

        <div className="flex items-center gap-1.5">
          <input
            ref={importInputRef}
            type="file"
            accept=".srt"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void handleImportFile(file)
              e.target.value = ''
            }}
          />
          <Button
            variant="secondary"
            title="Translate all subtitles with Google Cloud Translation"
            onClick={() => {
              setNotice(null)
              setShowTranslate(true)
            }}
            disabled={editor.subs.length === 0}
          >
            <Languages size={15} /> Translate
          </Button>
          <Button
            variant="secondary"
            title="Import an external .srt file — preview & edit it like transcribed subtitles"
            onClick={() => importInputRef.current?.click()}
            disabled={importing}
          >
            {importing ? <Spinner className="h-3.5 w-3.5" /> : <FileUp size={15} />}{' '}
            Import SRT
          </Button>
          <Button
            variant="secondary"
            title="Regenerate from the AI transcript (discards manual edits)"
            disabled={reprocessing}
            onClick={async () => {
              if (
                !window.confirm(
                  'Reprocess regenerates subtitles from the original AI transcript. Manual edits will be lost. Continue?',
                )
              ) {
                return
              }
              setReprocessing(true)
              setActionError(null)
              try {
                // flush pending edits first so a debounced auto-save cannot
                // overwrite the reprocessed rows afterwards
                await editor.save()
                await api.reprocessSubtitles(jobId!)
                await reloadSubtitles()
              } catch (error) {
                setActionError(
                  error instanceof Error ? error.message : 'Reprocess failed',
                )
              } finally {
                setReprocessing(false)
              }
            }}
          >
            {reprocessing ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : (
              <RefreshCw size={15} />
            )}{' '}
            Reprocess
          </Button>
        </div>
      </div>

      {actionError ? (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1 break-words">{actionError}</span>
          <button
            onClick={() => setActionError(null)}
            aria-label="Dismiss"
            className="rounded-md p-1 transition-colors hover:bg-danger/15"
          >
            <X size={14} />
          </button>
        </div>
      ) : null}

      {notice ? (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-success/30 bg-success/5 px-3.5 py-2.5 text-sm text-success"
        >
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1 break-words">{notice}</span>
          <button
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="rounded-md p-1 transition-colors hover:bg-success/10"
          >
            <X size={14} />
          </button>
        </div>
      ) : null}

      {showTranslate ? (
        <TranslateDialog
          jobId={jobId!}
          subtitleCount={editor.subs.length}
          pendingChars={pendingChars}
          detectedLanguage={job.data.detected_language ?? job.data.language}
          onBeforeTranslate={editor.save}
          onApply={(result) => {
            const changed = editor.applyTranslation(result.subtitles, result.mode)
            const from = languageName(
              result.source_language ?? result.detected_source_language,
            )
            const to = languageName(result.target_language)
            const usage = result.usage
            const budget =
              usage.monthly_char_limit > 0
                ? ` · ${usage.characters_sent.toLocaleString()} / ${usage.monthly_char_limit.toLocaleString()} chars this month`
                : ` · ${usage.characters_sent.toLocaleString()} chars this month`
            setNotice(
              `Translated ${result.translated} of ${result.total} subtitles (${from} → ${to})` +
                budget +
                (changed === 0 ? ' — no visible changes.' : '. Undo with Ctrl+Z.'),
            )
            setShowTranslate(false)
          }}
          onClose={() => setShowTranslate(false)}
        />
      ) : null}

      {showRender ? (
        <BurnInVideo
          jobId={jobId!}
          onBeforeStart={editor.save}
          onClose={() => setShowRender(false)}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        {/* left: video + timeline + warnings */}
        <div className="space-y-3">
          {job.data.media_id ? (
            <EditorVideoPlayer
              mediaId={job.data.media_id}
              subtitles={editor.subs}
              currentMs={currentMs}
              videoRef={videoRef}
              onTimeUpdate={setCurrentMs}
              onDurationChange={setDurationMs}
            />
          ) : null}

          <Timeline
            durationMs={durationMs}
            currentMs={currentMs}
            subtitles={editor.subs}
            activeKey={activeKey}
            selectedKey={selectedKey}
            onSeek={seek}
            onSelect={(key) => {
              // clicking a timeline block: select the row and bring it into
              // view (centered - the jump can be far from the current scroll)
              setSelectedKey(key)
              scrollToRow(key, 'center')
            }}
          />

          {/* warnings panel (§11.6) */}
          {totalIssues > 0 ? (
            <button
              onClick={() => setShowWarnings((v) => !v)}
              className="flex w-full items-center gap-2 rounded-lg border border-warning/40 bg-warning/5 px-4 py-2.5 text-left text-sm text-warning"
            >
              <AlertTriangle size={15} />
              <span className="font-medium">
                {totalIssues} quality warning{totalIssues === 1 ? '' : 's'}
              </span>
              <span className="text-xs text-muted">
                {showWarnings ? 'hide details' : 'show details'}
              </span>
            </button>
          ) : (
            <div className="rounded-lg border border-success/30 bg-success/5 px-4 py-2.5 text-sm text-success">
              All quality checks pass.
            </div>
          )}

          {showWarnings && totalIssues > 0 ? (
            <Card className="nice-scroll max-h-52 overflow-y-auto">
              <ul className="divide-y divide-line text-sm">
                {editor.subs
                  .map((sub, index) => ({ sub, index, list: issues.get(sub.key) ?? [] }))
                  .filter(({ list }) => list.length > 0)
                  .map(({ sub, index, list }) => (
                    <li key={sub.key}>
                      <button
                        className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-surface-2/50"
                        onClick={() => {
                          setSelectedKey(sub.key)
                          seek(sub.start_ms + 10)
                        }}
                      >
                        <span className="w-7 text-right font-mono text-[11px] text-muted">
                          {index + 1}
                        </span>
                        <span className="flex flex-wrap gap-1.5">
                          {list.map((issue, i) => (
                            <Badge key={i} tone="warning">
                              {ISSUE_LABELS[issue.code] ?? issue.code}
                            </Badge>
                          ))}
                        </span>
                        <span className="ml-auto truncate text-xs text-muted">
                          {sub.text.slice(0, 40) || '(empty)'}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </Card>
          ) : null}

          <p className="hidden flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted sm:flex">
            <Shortcut keys="Space">play/pause</Shortcut>
            <Shortcut keys="↑ ↓">navigate</Shortcut>
            <Shortcut keys="Del">remove</Shortcut>
            <Shortcut keys="Ctrl+Z/Y">undo/redo</Shortcut>
            <Shortcut keys="Ctrl+S">save</Shortcut>
          </p>
        </div>

        {/* right: subtitle list */}
        <Card className={cn('flex max-h-[70dvh] flex-col lg:max-h-[calc(100dvh-8rem)]')}>
          {showSearch ? (
            <SearchReplace
              onClose={() => {
                setShowSearch(false)
                setSearch('')
              }}
              onReplaceAll={(find, replace) => {
                const count = editor.replaceAllText(find, replace)
                setSearch('')
                return count
              }}
            />
          ) : null}

          {subtitlesQuery.isLoading && !editor.loaded ? (
            <div className="flex items-center justify-center gap-2 p-8 text-sm text-muted">
              <Spinner /> Loading subtitles…
            </div>
          ) : editor.subs.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted">
              No subtitles. Add one with the Add button.
            </div>
          ) : (
            <ul className="nice-scroll flex-1 overflow-y-auto">
              {editor.subs.map((sub, index) => (
                <SubtitleRow
                  key={sub.key}
                  sub={sub}
                  index={index}
                  selected={sub.key === selectedKey}
                  active={sub.key === activeKey}
                  issues={issues.get(sub.key) ?? []}
                  isLast={index === editor.subs.length - 1}
                  search={search}
                  onSelect={() => selectRow(sub.key, sub.start_ms)}
                  onTextChange={(text) => editor.setText(sub.key, text)}
                  onTimesChange={(start, end) => editor.setTimes(sub.key, start, end)}
                  onSplit={() => {
                    const key = editor.splitAtPlayhead(sub.key, currentMs)
                    if (key) setSelectedKey(key)
                  }}
                  onMerge={() => {
                    const key = editor.mergeWithNext(sub.key)
                    if (key) setSelectedKey(key)
                  }}
                  onDelete={() => {
                    editor.remove(sub.key)
                    selectIndex(Math.min(index, editor.subs.length - 2))
                  }}
                />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function ToolbarDivider() {
  return <span className="mx-0.5 h-6 w-px shrink-0 bg-line" aria-hidden />
}

function Shortcut({ keys, children }: { keys: string; children: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <kbd className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted">
        {keys}
      </kbd>
      {children}
    </span>
  )
}

function SaveIndicator({
  dirty,
  saving,
  savedAt,
  error,
}: {
  dirty: boolean
  saving: boolean
  savedAt: number | null
  error: string | null
}) {
  if (error) {
    return <Badge tone="danger">Save failed — retrying on next change</Badge>
  }
  if (saving) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-muted">
        <Spinner className="h-3 w-3" /> Saving…
      </span>
    )
  }
  if (dirty) {
    return <Badge tone="info">Unsaved changes</Badge>
  }
  return (
    <span className="text-xs text-muted">
      Saved{savedAt ? ` · ${new Date(savedAt).toLocaleTimeString()}` : ''}
    </span>
  )
}
