// Subtitle editor state: working copy, undo/redo history, and debounced
// full-state auto-save (§11.5). The working copy is the source of truth
// while editing; auto-save syncs it to the backend atomically.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../api/client'
import type { Subtitle, SyncSubtitleItem, TranslateMode, TranslatedTextItem } from '../../types'
import { clamp } from './time'

export interface EditorSubtitle {
  key: string
  start_ms: number
  end_ms: number
  text: string
  original_text: string
  is_edited: boolean
}

const HISTORY_LIMIT = 200
const AUTOSAVE_DELAY_MS = 1200
const COALESCE_WINDOW_MS = 900

function fromApi(subs: Subtitle[]): EditorSubtitle[] {
  return subs.map((s) => ({
    key: s.id,
    start_ms: s.start_ms,
    end_ms: s.end_ms,
    text: s.text,
    original_text: s.original_text,
    is_edited: s.is_edited,
  }))
}

function newKey(): string {
  return crypto.randomUUID()
}

export function splitTextAtRatio(text: string, ratio: number): [string, string] {
  const trimmed = text.trim()
  if (!trimmed) return ['', '']
  if (trimmed.includes(' ')) {
    const words = trimmed.split(/\s+/)
    const total = words.join(' ').length
    let acc = 0
    for (let i = 0; i < words.length; i++) {
      acc += words[i].length + (i > 0 ? 1 : 0)
      if (acc / total >= ratio) {
        if (i === words.length - 1) return [trimmed, '']
        return [words.slice(0, i + 1).join(' '), words.slice(i + 1).join(' ')]
      }
    }
  }
  // no spaces (e.g. Thai): cut at the character boundary
  const cut = clamp(Math.round(trimmed.length * ratio), 1, trimmed.length - 1)
  return [trimmed.slice(0, cut), trimmed.slice(cut)]
}

export function useSubtitleEditor(jobId: string | undefined) {
  const [subs, setSubs] = useState<EditorSubtitle[]>([])
  const [past, setPast] = useState<EditorSubtitle[][]>([])
  const [future, setFuture] = useState<EditorSubtitle[][]>([])
  const [savedJson, setSavedJson] = useState('[]')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const subsRef = useRef(subs)
  subsRef.current = subs
  const coalesceMeta = useRef<{ key: string; field: string; at: number } | null>(null)

  const json = useMemo(() => JSON.stringify(subs), [subs])
  const dirty = json !== savedJson && savedJson !== '' // '' = never loaded
  const loaded = savedJson !== ''

  // ---------------------------------------------------------------- history
  const commit = useCallback(
    (next: EditorSubtitle[], meta?: { key: string; field: string }) => {
      const now = Date.now()
      const last = coalesceMeta.current
      const canCoalesce =
        meta !== undefined &&
        last !== null &&
        last.key === meta.key &&
        last.field === meta.field &&
        now - last.at < COALESCE_WINDOW_MS

      if (!canCoalesce) {
        setPast((prev) => [...prev.slice(-(HISTORY_LIMIT - 1)), subsRef.current])
      }
      if (meta) coalesceMeta.current = { ...meta, at: now }
      else coalesceMeta.current = null
      setFuture([])
      setSubs(next)
    },
    [],
  )

  const undo = useCallback(() => {
    setPast((prev) => {
      if (prev.length === 0) return prev
      const previous = prev[prev.length - 1]
      setFuture((f) => [subsRef.current, ...f])
      setSubs(previous)
      return prev.slice(0, -1)
    })
    coalesceMeta.current = null
  }, [])

  const redo = useCallback(() => {
    setFuture((prev) => {
      if (prev.length === 0) return prev
      const next = prev[0]
      setPast((p) => [...p, subsRef.current])
      setSubs(next)
      return prev.slice(1)
    })
    coalesceMeta.current = null
  }, [])

  // ---------------------------------------------------------------- loading
  const accept = useCallback((serverSubs: Subtitle[]) => {
    const converted = fromApi(serverSubs)
    subsRef.current = converted
    setSubs(converted)
    setSavedJson(JSON.stringify(converted))
    setPast([])
    setFuture([])
    coalesceMeta.current = null
  }, [])

  // ------------------------------------------------------------ operations
  const setText = useCallback(
    (key: string, text: string) => {
      const next = subsRef.current.map((s) =>
        s.key === key
          ? { ...s, text, is_edited: text !== s.original_text || s.is_edited }
          : s,
      )
      commit(next, { key, field: 'text' })
    },
    [commit],
  )

  const setTimes = useCallback(
    (key: string, startMs: number, endMs: number): boolean => {
      if (startMs < 0 || endMs <= startMs) return false
      const next = subsRef.current.map((s) =>
        s.key === key ? { ...s, start_ms: startMs, end_ms: endMs, is_edited: true } : s,
      )
      commit(next)
      return true
    },
    [commit],
  )

  const addAfter = useCallback(
    (key: string | null): string | null => {
      const current = subsRef.current
      const index = key ? current.findIndex((s) => s.key === key) : current.length - 1
      const insertAt = index + 1
      const prev = current[index]
      const start = prev ? prev.end_ms + 50 : 0
      const fresh: EditorSubtitle = {
        key: newKey(),
        start_ms: start,
        end_ms: start + 1500,
        text: '',
        original_text: '',
        is_edited: false,
      }
      const next = [...current.slice(0, insertAt), fresh, ...current.slice(insertAt)]
      commit(next)
      return fresh.key
    },
    [commit],
  )

  const remove = useCallback(
    (key: string) => {
      commit(subsRef.current.filter((s) => s.key !== key))
    },
    [commit],
  )

  const splitAtPlayhead = useCallback(
    (key: string, playheadMs: number): string | null => {
      const current = subsRef.current
      const index = current.findIndex((s) => s.key === key)
      if (index === -1) return null
      const row = current[index]
      if (row.end_ms - row.start_ms < 300) return null
      const boundary = clamp(playheadMs, row.start_ms + 100, row.end_ms - 100)
      const ratio = (boundary - row.start_ms) / (row.end_ms - row.start_ms)
      const [leftText, rightText] = splitTextAtRatio(row.text, ratio)
      const left: EditorSubtitle = {
        ...row,
        end_ms: boundary,
        text: leftText,
        is_edited: true,
      }
      const right: EditorSubtitle = {
        ...row,
        key: newKey(),
        start_ms: boundary + 50,
        text: rightText,
        is_edited: true,
      }
      const next = [...current.slice(0, index), left, right, ...current.slice(index + 1)]
      commit(next)
      return right.key
    },
    [commit],
  )

  const mergeWithNext = useCallback(
    (key: string): string | null => {
      const current = subsRef.current
      const index = current.findIndex((s) => s.key === key)
      if (index === -1 || index === current.length - 1) return null
      const a = current[index]
      const b = current[index + 1]
      const merged: EditorSubtitle = {
        key: a.key,
        start_ms: Math.min(a.start_ms, b.start_ms),
        end_ms: Math.max(a.end_ms, b.end_ms),
        text: [a.text.trim(), b.text.trim()].filter(Boolean).join(' '),
        original_text: a.original_text,
        is_edited: true,
      }
      const next = [...current.slice(0, index), merged, ...current.slice(index + 2)]
      commit(next)
      return merged.key
    },
    [commit],
  )

  const replaceAllText = useCallback(
    (search: string, replacement: string): number => {
      if (!search) return 0
      let count = 0
      const next = subsRef.current.map((s) => {
        if (!s.text.includes(search)) return s
        count += 1
        const text = s.text.split(search).join(replacement)
        return { ...s, text, is_edited: text !== s.original_text || s.is_edited }
      })
      if (count > 0) commit(next)
      return count
    },
    [commit],
  )

  /** Apply translation results (1-based indexes aligned to the saved list).
   *
   * 'replace' swaps the cue text for the translation; 'dual' appends the
   * translation on a new line below the original (bilingual subtitles).
   * Applied as ONE undo step; auto-save persists it like any other edit.
   */
  const applyTranslation = useCallback(
    (items: TranslatedTextItem[], mode: TranslateMode): number => {
      let changed = 0
      const byIndex = new Map(items.map((item) => [item.index, item.text]))
      const next = subsRef.current.map((s, i) => {
        const translated = byIndex.get(i + 1)
        if (translated === undefined || !translated) return s
        const text =
          mode === 'dual' && s.text.trim() ? `${s.text.trimEnd()}\n${translated}` : translated
        if (text === s.text) return s
        changed += 1
        return { ...s, text, is_edited: true }
      })
      if (changed > 0) commit(next)
      return changed
    },
    [commit],
  )

  // ------------------------------------------------------------ persistence
  const save = useCallback(async (): Promise<boolean> => {
    if (!jobId || !loaded) return false
    if (JSON.stringify(subsRef.current) === savedJson) return true
    setSaving(true)
    setSaveError(null)
    try {
      const payload: SyncSubtitleItem[] = subsRef.current.map((s, i) => ({
        subtitle_index: i + 1,
        start_ms: s.start_ms,
        end_ms: s.end_ms,
        text: s.text,
        original_text: s.original_text,
        is_edited: s.is_edited,
      }))
      await api.syncSubtitles(jobId, payload)
      setSavedJson(JSON.stringify(subsRef.current))
      setSavedAt(Date.now())
      return true
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Save failed')
      return false
    } finally {
      setSaving(false)
    }
  }, [jobId, loaded, savedJson])

  // debounced auto-save
  useEffect(() => {
    if (!dirty || saving || !jobId) return
    const timer = window.setTimeout(() => {
      void save()
    }, AUTOSAVE_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [dirty, saving, jobId, save])

  return {
    subs,
    loaded,
    dirty,
    saving,
    savedAt,
    saveError,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    accept,
    undo,
    redo,
    save,
    setText,
    setTimes,
    addAfter,
    remove,
    splitAtPlayhead,
    mergeWithNext,
    replaceAllText,
    applyTranslation,
  }
}
