// Component test for the Processing-page equalizer hero.

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { EqualizerBars } from './EqualizerBars'

afterEach(() => {
  cleanup() // vitest runs without globals, so RTL auto-cleanup is off
})

describe('EqualizerBars', () => {
  it('renders five bars', () => {
    const { container } = render(<EqualizerBars active />)
    expect(container.querySelectorAll('.eq-bar')).toHaveLength(5)
  })

  it('animates with the accent colour while active', () => {
    const { container } = render(<EqualizerBars active />)
    const first = container.querySelector('.eq-bar')
    expect(first).toHaveClass('eq-bar-active', 'bg-accent')
    expect(first).not.toHaveClass('bg-line')
  })

  it('rests on the static staircase while inactive', () => {
    const { container } = render(<EqualizerBars active={false} />)
    const first = container.querySelector('.eq-bar')
    expect(first).not.toHaveClass('eq-bar-active')
    expect(first).toHaveClass('bg-line')
  })

  it('is hidden from assistive tech', () => {
    const { container } = render(<EqualizerBars active />)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })
})
