// Component test for the search & replace bar (§11.5).

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SearchReplace from './SearchReplace'

function setup(replaceCount: number) {
  const onReplaceAll = vi.fn(() => replaceCount)
  const onClose = vi.fn()
  render(<SearchReplace onReplaceAll={onReplaceAll} onClose={onClose} />)
  return { onReplaceAll, onClose }
}

afterEach(() => {
  cleanup() // vitest runs without globals, so RTL auto-cleanup is off
})

describe('SearchReplace', () => {
  it('replaces and reports the affected subtitle count', async () => {
    const user = userEvent.setup()
    const { onReplaceAll } = setup(2)

    await user.type(screen.getByPlaceholderText('Find'), 'teh')
    await user.type(screen.getByPlaceholderText('Replace with'), 'the')
    await user.click(screen.getByRole('button', { name: /replace all/i }))

    expect(onReplaceAll).toHaveBeenCalledWith('teh', 'the')
    expect(screen.getByText('Replaced in 2 subtitles')).toBeInTheDocument()
  })

  it('reports when nothing matched', async () => {
    const user = userEvent.setup()
    const { onReplaceAll } = setup(0)

    await user.type(screen.getByPlaceholderText('Find'), 'zzz')
    await user.click(screen.getByRole('button', { name: /replace all/i }))

    expect(onReplaceAll).toHaveBeenCalledWith('zzz', '')
    expect(screen.getByText('No matches')).toBeInTheDocument()
  })

  it('disables the button until a search term is typed', async () => {
    const user = userEvent.setup()
    const { onReplaceAll } = setup(1)

    const button = screen.getByRole('button', { name: /replace all/i })
    expect(button).toBeDisabled()
    await user.type(screen.getByPlaceholderText('Find'), 'a')
    expect(button).toBeEnabled()
    expect(onReplaceAll).not.toHaveBeenCalled()
  })

  it('clears the previous result when the inputs change again', async () => {
    const user = userEvent.setup()
    setup(1)

    await user.type(screen.getByPlaceholderText('Find'), 'a')
    await user.click(screen.getByRole('button', { name: /replace all/i }))
    expect(screen.getByText('Replaced in 1 subtitle')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('Find'), 'b')
    expect(screen.queryByText('Replaced in 1 subtitle')).not.toBeInTheDocument()
  })

  it('closes via the Close button', async () => {
    const user = userEvent.setup()
    const { onClose } = setup(0)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
