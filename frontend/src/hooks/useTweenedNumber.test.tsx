// Tests for the tweened-number hook (Processing % readout): the snap
// cases (mount / zero duration / backwards target / reduced motion) and
// the upward glide between polls.

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useTweenedNumber } from './useTweenedNumber'

const originalMatchMedia = window.matchMedia

/** Re-stub matchMedia the way setup.ts installs it (writable, full shape). */
function stubMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

afterEach(() => {
  cleanup() // vitest runs without globals, so RTL auto-cleanup is off
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: originalMatchMedia,
  })
})

describe('useTweenedNumber', () => {
  it('snaps to the target on mount', () => {
    const { result } = renderHook(() => useTweenedNumber(57, 900))
    expect(result.current).toBe(57)
  })

  it('snaps when durationMs <= 0', () => {
    const { result, rerender } = renderHook(
      ({ t }: { t: number }) => useTweenedNumber(t, 0),
      { initialProps: { t: 0 } },
    )
    act(() => rerender({ t: 40 }))
    expect(result.current).toBe(40)
  })

  it('snaps when the target moves backwards (retry / new job)', () => {
    const { result, rerender } = renderHook(
      ({ t }: { t: number }) => useTweenedNumber(t, 900),
      { initialProps: { t: 80 } },
    )
    act(() => rerender({ t: 10 }))
    expect(result.current).toBe(10)
  })

  it('snaps under reduced motion', () => {
    stubMatchMedia(true)
    const { result, rerender } = renderHook(
      ({ t }: { t: number }) => useTweenedNumber(t, 900),
      { initialProps: { t: 10 } },
    )
    act(() => rerender({ t: 80 }))
    expect(result.current).toBe(80)
  })

  it('glides upward toward a higher target', async () => {
    const { result, rerender } = renderHook(
      ({ t }: { t: number }) => useTweenedNumber(t, 60),
      { initialProps: { t: 0 } },
    )
    rerender({ t: 100 })

    await waitFor(() => expect(result.current).toBe(100), { timeout: 2000 })
  })
})
