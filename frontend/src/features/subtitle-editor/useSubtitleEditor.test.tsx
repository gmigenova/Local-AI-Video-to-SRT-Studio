// Tests for the editor state hook: history (undo/redo + typing coalescing),
// debounced auto-save, and the apply-operations. The API client is mocked —
// sync must be the ONLY network path exercised here.

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Subtitle } from '../../types'
import { useSubtitleEditor } from './useSubtitleEditor'

const mocks = vi.hoisted(() => ({ sync: vi.fn() }))

vi.mock('../../api/client', () => ({
  api: { syncSubtitles: mocks.sync },
}))

function serverSubs(): Subtitle[] {
  return [
    {
      id: 'a',
      subtitle_index: 1,
      start_ms: 0,
      end_ms: 2000,
      text: 'Hello',
      original_text: 'Hello',
      is_edited: false,
      speaker: null,
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 'b',
      subtitle_index: 2,
      start_ms: 2100,
      end_ms: 4000,
      text: 'World',
      original_text: 'World',
      is_edited: false,
      speaker: null,
      updated_at: '2026-01-01T00:00:00Z',
    },
  ]
}

function setup(jobId = 'job-1') {
  const hook = renderHook(() => useSubtitleEditor(jobId))
  act(() => hook.result.current.accept(serverSubs()))
  return hook
}

beforeEach(() => {
  mocks.sync.mockReset()
  mocks.sync.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup() // vitest runs without globals, so RTL auto-cleanup is off
  vi.useRealTimers()
})

describe('useSubtitleEditor — loading', () => {
  it('starts empty and clean (initial state counts as a saved empty list)', () => {
    const { result } = renderHook(() => useSubtitleEditor('job-1'))
    expect(result.current.subs).toEqual([])
    expect(result.current.dirty).toBe(false)
    expect(result.current.canUndo).toBe(false)
    expect(result.current.canRedo).toBe(false)
  })

  it('accept() loads rows as clean state with empty history', () => {
    const { result } = setup()
    expect(result.current.loaded).toBe(true)
    expect(result.current.dirty).toBe(false)
    expect(result.current.canUndo).toBe(false)
    expect(result.current.subs).toHaveLength(2)
  })
})

describe('useSubtitleEditor — history', () => {
  it('undo reverts an edit and redo restores it', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hola'))
    expect(result.current.subs[0].text).toBe('Hola')
    expect(result.current.dirty).toBe(true)

    act(() => result.current.undo())
    expect(result.current.subs[0].text).toBe('Hello')
    expect(result.current.canRedo).toBe(true)

    act(() => result.current.redo())
    expect(result.current.subs[0].text).toBe('Hola')
    expect(result.current.canRedo).toBe(false)
  })

  it('coalesces rapid typing on the same field into one undo step', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'H'))
    act(() => result.current.setText('a', 'He'))
    act(() => result.current.setText('a', 'Hel'))
    act(() => result.current.undo())
    // ONE undo reverts the whole typing burst
    expect(result.current.subs[0].text).toBe('Hello')
    expect(result.current.canUndo).toBe(false)
  })

  it('starts a new history entry after the coalesce window passes', () => {
    vi.useFakeTimers()
    const { result } = setup()
    act(() => result.current.setText('a', 'H'))
    act(() => {
      vi.advanceTimersByTime(901)
    })
    act(() => result.current.setText('a', 'He'))
    act(() => result.current.undo())
    expect(result.current.subs[0].text).toBe('H') // only the second burst undone
    act(() => result.current.undo())
    expect(result.current.subs[0].text).toBe('Hello')
  })

  it('does not coalesce edits on different fields or rows', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hola'))
    act(() => result.current.setText('b', 'Mundo'))
    act(() => result.current.undo())
    expect(result.current.subs[1].text).toBe('World') // second edit undone only
  })

  it('clears the redo stack on a fresh edit', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hola'))
    act(() => result.current.undo())
    act(() => result.current.setText('b', 'Mundo'))
    expect(result.current.canRedo).toBe(false)
  })
})

describe('useSubtitleEditor — operations', () => {
  it('setText marks the row edited only when it differs from the original', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hello')) // same as original
    expect(result.current.subs[0].is_edited).toBe(false)
    act(() => result.current.setText('a', 'Hola'))
    expect(result.current.subs[0].is_edited).toBe(true)
  })

  it('setTimes rejects invalid ranges without touching state', () => {
    const { result } = setup()
    let ok = false
    act(() => {
      ok = result.current.setTimes('a', 5000, 4000)
    })
    expect(ok).toBe(false)
    expect(result.current.subs[0].start_ms).toBe(0)
    expect(result.current.canUndo).toBe(false)
    act(() => {
      ok = result.current.setTimes('a', 100, 900)
    })
    expect(ok).toBe(true)
    expect(result.current.subs[0].start_ms).toBe(100)
  })

  it('addAfter inserts a blank row after the target (or at the end)', () => {
    const { result } = setup()
    let key = ''
    act(() => {
      key = result.current.addAfter('a') ?? ''
    })
    expect(result.current.subs).toHaveLength(3)
    expect(result.current.subs[1].key).toBe(key)
    expect(result.current.subs[1].start_ms).toBe(2050) // prev end + 50
    act(() => {
      key = result.current.addAfter(null) ?? ''
    })
    expect(result.current.subs[3].key).toBe(key)
  })

  it('remove deletes a row', () => {
    const { result } = setup()
    act(() => result.current.remove('a'))
    expect(result.current.subs.map((s) => s.key)).toEqual(['b'])
  })

  it('splitAtPlayhead divides text and timing at the boundary', () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hello there foo'))
    let rightKey = ''
    act(() => {
      rightKey = result.current.splitAtPlayhead('a', 1000) ?? ''
    })
    expect(result.current.subs).toHaveLength(3)
    const [left, right] = result.current.subs
    expect(left.text).toBe('Hello there') // word-boundary split at ratio 0.5
    expect(right.text).toBe('foo')
    expect(left.end_ms).toBe(1000)
    expect(right.start_ms).toBe(1050) // boundary + gap
    expect(right.key).toBe(rightKey)
    expect(right.key).not.toBe('a')
  })

  it('splitAtPlayhead refuses rows shorter than 300 ms', () => {
    const { result } = setup()
    act(() => result.current.setTimes('a', 0, 200)) // duration 200 < 300
    let key: string | null = 'x'
    act(() => {
      key = result.current.splitAtPlayhead('a', 100)
    })
    expect(key).toBeNull()
    expect(result.current.subs).toHaveLength(2)
  })

  it('mergeWithNext joins text and span, keeping the first key', () => {
    const { result } = setup()
    let key = ''
    act(() => {
      key = result.current.mergeWithNext('a') ?? ''
    })
    expect(result.current.subs).toHaveLength(1)
    const merged = result.current.subs[0]
    expect(merged.key).toBe('a')
    expect(key).toBe('a')
    expect(merged.text).toBe('Hello World')
    expect(merged.start_ms).toBe(0)
    expect(merged.end_ms).toBe(4000)
  })

  it('mergeWithNext returns null for the last row', () => {
    const { result } = setup()
    let key: string | null = 'x'
    act(() => {
      key = result.current.mergeWithNext('b')
    })
    expect(key).toBeNull()
  })

  it('replaceAllText counts affected rows and skips non-matching ones', () => {
    const { result } = setup()
    let count = 0
    act(() => {
      count = result.current.replaceAllText('o', '0')
    })
    expect(count).toBe(2)
    expect(result.current.subs[0].text).toBe('Hell0')
    expect(result.current.subs[1].text).toBe('W0rld')
    act(() => {
      count = result.current.replaceAllText('zzz', 'x')
    })
    expect(count).toBe(0)
    expect(result.current.canUndo).toBe(true) // only the first replace committed
  })

  it('replaceAllText ignores an empty search', () => {
    const { result } = setup()
    let count = -1
    act(() => {
      count = result.current.replaceAllText('', 'x')
    })
    expect(count).toBe(0)
    expect(result.current.canUndo).toBe(false)
  })
})

describe('useSubtitleEditor — applyTranslation', () => {
  it('replaces cue texts by 1-based index as ONE undo step', () => {
    const { result } = setup()
    let changed = 0
    act(() => {
      changed = result.current.applyTranslation(
        [
          { index: 1, text: 'สวัสดี' },
          { index: 2, text: 'โลก' },
        ],
        'replace',
      )
    })
    expect(changed).toBe(2)
    expect(result.current.subs[0].text).toBe('สวัสดี')
    expect(result.current.subs[1].text).toBe('โลก')

    act(() => result.current.undo()) // one step restores BOTH rows
    expect(result.current.subs[0].text).toBe('Hello')
    expect(result.current.subs[1].text).toBe('World')
  })

  it("'dual' mode appends the translation under the original", () => {
    const { result } = setup()
    act(() => {
      result.current.applyTranslation([{ index: 1, text: 'สวัสดี' }], 'dual')
    })
    expect(result.current.subs[0].text).toBe('Hello\nสวัสดี')
  })

  it('ignores blank translations and out-of-range indexes', () => {
    const { result } = setup()
    let changed = 0
    act(() => {
      changed = result.current.applyTranslation(
        [
          { index: 1, text: '' },
          { index: 99, text: 'nope' },
        ],
        'replace',
      )
    })
    expect(changed).toBe(0)
    expect(result.current.dirty).toBe(false)
    expect(result.current.canUndo).toBe(false)
  })
})

describe('useSubtitleEditor — applyCleanup', () => {
  it('replaces cue texts by 1-based index as ONE undo step', () => {
    const { result } = setup()
    let changed = 0
    act(() => {
      changed = result.current.applyCleanup([
        { index: 1, text: 'Hello, world!' },
        { index: 2, text: 'World!' },
      ])
    })
    expect(changed).toBe(2)
    expect(result.current.subs[0].text).toBe('Hello, world!')
    expect(result.current.subs[1].text).toBe('World!')

    act(() => result.current.undo()) // one step restores BOTH rows
    expect(result.current.subs[0].text).toBe('Hello')
    expect(result.current.subs[1].text).toBe('World')
  })

  it('ignores blank results and counts unchanged texts', () => {
    const { result } = setup()
    let changed = 0
    act(() => {
      changed = result.current.applyCleanup([
        { index: 1, text: '' }, // blank: ignored
        { index: 2, text: 'World' }, // identical: not a change
      ])
    })
    expect(changed).toBe(0)
    expect(result.current.dirty).toBe(false)
    expect(result.current.canUndo).toBe(false)
  })

  it('never touches timestamps', () => {
    const { result } = setup()
    act(() => result.current.applyCleanup([{ index: 1, text: 'Hola' }]))
    expect(result.current.subs[0].start_ms).toBe(0)
    expect(result.current.subs[0].end_ms).toBe(2000)
  })
})

describe('useSubtitleEditor — speakers', () => {
  it('setSpeaker sets and clears labels (coalesced like typing)', () => {
    const { result } = setup()
    act(() => result.current.setSpeaker('a', 'Host'))
    expect(result.current.subs[0].speaker).toBe('Host')
    act(() => result.current.undo())
    expect(result.current.subs[0].speaker).toBeNull()
    act(() => result.current.redo())
    expect(result.current.subs[0].speaker).toBe('Host')

    // rapid changes on the same field coalesce into ONE undo step
    act(() => result.current.setSpeaker('a', null))
    act(() => result.current.setSpeaker('a', 'Guest'))
    act(() => result.current.undo())
    expect(result.current.subs[0].speaker).toBe('Host')
  })

  it('applySpeakerRename renames across rows as ONE undo step', () => {
    const { result } = setup()
    act(() => result.current.setSpeaker('a', 'SPEAKER_00'))
    act(() => result.current.setSpeaker('b', 'SPEAKER_01'))
    let changed = 0
    act(() => {
      changed = result.current.applySpeakerRename({ SPEAKER_00: 'Host', SPEAKER_01: 'Guest' })
    })
    expect(changed).toBe(2)
    expect(result.current.subs[0].speaker).toBe('Host')
    expect(result.current.subs[1].speaker).toBe('Guest')

    act(() => result.current.undo()) // one step restores BOTH rows
    expect(result.current.subs[0].speaker).toBe('SPEAKER_00')
    expect(result.current.subs[1].speaker).toBe('SPEAKER_01')
  })

  it('applySpeakerRename with an empty value clears the label', () => {
    const { result } = setup()
    act(() => result.current.setSpeaker('a', 'SPEAKER_00'))
    act(() => result.current.applySpeakerRename({ SPEAKER_00: '  ' }))
    expect(result.current.subs[0].speaker).toBeNull()
  })

  it('addAfter and split inherit the source row speaker', () => {
    const { result } = setup()
    act(() => result.current.setSpeaker('a', 'Host'))
    act(() => result.current.addAfter('a'))
    expect(result.current.subs[1].speaker).toBe('Host')

    act(() => result.current.splitAtPlayhead('a', 1000))
    expect(result.current.subs[0].speaker).toBe('Host')
    expect(result.current.subs[1].speaker).toBe('Host')
  })

  it('mergeWithNext keeps the first row speaker, falling back to the next', () => {
    const { result } = setup()
    act(() => result.current.setSpeaker('b', 'Guest'))
    act(() => result.current.mergeWithNext('a'))
    expect(result.current.subs[0].speaker).toBe('Guest') // a had none -> b's label
  })
})

describe('useSubtitleEditor — persistence', () => {
  it('auto-saves once after the debounce delay, with a 1-based payload', async () => {
    vi.useFakeTimers()
    const { result } = setup()
    act(() => result.current.setText('a', 'Hola'))
    expect(mocks.sync).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(1199)
    })
    expect(mocks.sync).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(1)
    })
    expect(mocks.sync).toHaveBeenCalledTimes(1)
    expect(mocks.sync).toHaveBeenCalledWith('job-1', [
      {
        subtitle_index: 1,
        start_ms: 0,
        end_ms: 2000,
        text: 'Hola',
        original_text: 'Hello',
        is_edited: true,
        speaker: null,
      },
      {
        subtitle_index: 2,
        start_ms: 2100,
        end_ms: 4000,
        text: 'World',
        original_text: 'World',
        is_edited: false,
        speaker: null,
      },
    ])
    expect(result.current.dirty).toBe(false)
    expect(result.current.savedAt).not.toBeNull()

    // no further saves while clean
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(mocks.sync).toHaveBeenCalledTimes(1)
  })

  it('saves the latest state when the debounce fires, even mid-typing', async () => {
    vi.useFakeTimers()
    const { result } = setup()
    act(() => result.current.setText('a', 'H'))
    await act(async () => {
      vi.advanceTimersByTime(600)
    })
    act(() => result.current.setText('a', 'He')) // more typing before the deadline
    await act(async () => {
      vi.advanceTimersByTime(600)
    }) // 1200 ms after the edit that made the row dirty
    expect(mocks.sync).toHaveBeenCalledTimes(1)
    expect(mocks.sync.mock.calls[0][1][0].text).toBe('He') // latest text, not 'H'

    // a further edit schedules the next save round
    act(() => result.current.setText('a', 'Hel'))
    await act(async () => {
      vi.advanceTimersByTime(1200)
    })
    expect(mocks.sync).toHaveBeenCalledTimes(2)
    expect(mocks.sync.mock.calls[1][1][0].text).toBe('Hel')
  })

  it('manual save() flushes and reports failures cleanly', async () => {
    const { result } = setup()
    act(() => result.current.setText('a', 'Hola'))
    mocks.sync.mockRejectedValueOnce(new Error('disk full'))

    let ok = true
    await act(async () => {
      ok = await result.current.save()
    })
    expect(ok).toBe(false)
    expect(result.current.saveError).toBe('disk full')
    expect(result.current.dirty).toBe(true)
  })

  it('save() is a no-op when clean or when there is no job', async () => {
    const { result } = setup()
    let ok = false
    await act(async () => {
      ok = await result.current.save()
    })
    expect(ok).toBe(true)
    expect(mocks.sync).not.toHaveBeenCalled()

    const noJob = renderHook(() => useSubtitleEditor(undefined))
    await act(async () => {
      ok = await noJob.result.current.save()
    })
    expect(ok).toBe(false)
    expect(mocks.sync).not.toHaveBeenCalled()
  })
})
