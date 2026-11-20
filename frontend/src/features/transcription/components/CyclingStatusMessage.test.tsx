// Component test for the rotating status line under the Processing
// progress bar: cycling, wrap-around, reduced-motion pin, and the
// screen-reader split (stable sr-only line, aria-hidden cycling text).

import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CyclingStatusMessage } from './CyclingStatusMessage'

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
  vi.useRealTimers()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: originalMatchMedia,
  })
})

const MESSAGES = ['one', 'two', 'three']

function setup() {
  render(<CyclingStatusMessage srText="Stage: transcribing" messages={MESSAGES} />)
}

describe('CyclingStatusMessage', () => {
  it('shows the first message inside a polite live region', () => {
    setup()

    expect(screen.getByText('one')).toBeInTheDocument()
    const region = screen.getByRole('status')
    expect(region).toHaveAttribute('aria-live', 'polite')
    expect(region).toHaveTextContent('Stage: transcribing')
  })

  it('cycles to the next message every 2.4s', () => {
    vi.useFakeTimers()
    setup()

    act(() => vi.advanceTimersByTime(2400))
    expect(screen.getByText('two')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(2400))
    expect(screen.getByText('three')).toBeInTheDocument()
  })

  it('wraps around after the last message', () => {
    vi.useFakeTimers()
    setup()

    act(() => vi.advanceTimersByTime(3 * 2400))
    expect(screen.getByText('one')).toBeInTheDocument()
  })

  it('keeps the first message under reduced motion', () => {
    stubMatchMedia(true)
    vi.useFakeTimers()
    setup()

    act(() => vi.advanceTimersByTime(10_000))
    expect(screen.getByText('one')).toBeInTheDocument()
    expect(screen.queryByText('two')).not.toBeInTheDocument()
  })

  it('hides the cycling line from screen readers', () => {
    setup()

    expect(screen.getByText('one').closest('p')).toHaveAttribute(
      'aria-hidden',
      'true',
    )
  })
})
