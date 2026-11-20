// Component test for one editor row: compact display, expansion, issues,
// and the search highlight.

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { EditorSubtitle } from '../useSubtitleEditor'
import SubtitleRow from './SubtitleRow'

function sub(overrides: Partial<EditorSubtitle> = {}): EditorSubtitle {
  return {
    key: 'a',
    start_ms: 1000,
    end_ms: 3000,
    text: 'Hello world',
    original_text: 'Hello world',
    is_edited: false,
    speaker: null,
    ...overrides,
  }
}

type Props = Parameters<typeof SubtitleRow>[0]

function baseProps(overrides: Partial<Props> = {}): Props {
  return {
    sub: sub(),
    index: 0,
    selected: false,
    active: false,
    issues: [],
    isLast: false,
    search: '',
    knownSpeakers: [],
    onSelect: vi.fn(),
    onTextChange: vi.fn(),
    onTimesChange: vi.fn(),
    onSpeakerChange: vi.fn(),
    onSplit: vi.fn(),
    onMerge: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  }
}

afterEach(() => {
  cleanup() // vitest runs without globals, so RTL auto-cleanup is off
})

describe('SubtitleRow — compact', () => {
  it('renders the row number, timestamps, and text', () => {
    render(<SubtitleRow {...baseProps()} />)
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('00:00:01,000')).toBeInTheDocument()
    expect(screen.getByText('00:00:03,000')).toBeInTheDocument()
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('shows no editing panel until selected', () => {
    const utils = render(<SubtitleRow {...baseProps()} />)
    expect(screen.queryByPlaceholderText('Subtitle text…')).not.toBeInTheDocument()

    utils.rerender(<SubtitleRow {...baseProps({ selected: true })} />)
    expect(screen.getByPlaceholderText('Subtitle text…')).toBeInTheDocument()
  })

  it('invokes onSelect when the compact row is clicked', () => {
    const onSelect = vi.fn()
    render(<SubtitleRow {...baseProps({ onSelect })} />)
    fireEvent.click(screen.getByText('Hello world'))
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('highlights the search term with <mark>', () => {
    render(<SubtitleRow {...baseProps({ search: 'world' })} />)
    const mark = screen.getByText('world')
    expect(mark.tagName).toBe('MARK')
  })

  it('marks edited rows with a badge', () => {
    render(<SubtitleRow {...baseProps({ sub: sub({ is_edited: true }) })} />)
    expect(screen.getByText('edited')).toBeInTheDocument()
  })
})

describe('SubtitleRow — confidence', () => {
  const risky = [
    { word: 'world', probability: 0.42 },
    { word: 'maybe', probability: 0.55 },
  ]

  it('shows a low-conf badge with the risky word count (tooltip lists them)', () => {
    render(<SubtitleRow {...baseProps({ risky })} />)
    const badge = screen.getByText('2 low-conf')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('title', 'Words the AI was unsure about: world, maybe')
  })

  it('renders no badge when there are no risky words', () => {
    render(<SubtitleRow {...baseProps({ risky: [] })} />)
    expect(screen.queryByText(/low-conf/)).not.toBeInTheDocument()
  })

  it('marks risky words with <mark> only while the toggle is on', () => {
    const off = render(<SubtitleRow {...baseProps({ risky })} />)
    expect(off.getByText('Hello world').tagName).not.toBe('MARK')

    const on = render(
      <SubtitleRow {...baseProps({ risky, showConfidence: true })} />,
    )
    expect(on.getByText('world').tagName).toBe('MARK')
    expect(on.getByText('Hello').tagName).not.toBe('MARK') // plain chunk span
  })

  it('lists risky words with probabilities in the expanded panel', () => {
    render(
      <SubtitleRow
        {...baseProps({ selected: true, risky, showConfidence: true })}
      />,
    )
    expect(screen.getByText('Low-confidence words:')).toBeInTheDocument()
    expect(screen.getByText('world · 42%')).toBeInTheDocument()
    expect(screen.getByText('maybe · 55%')).toBeInTheDocument()
  })
})

describe('SubtitleRow — expanded', () => {
  it('edits text through the textarea', () => {
    const onTextChange = vi.fn()
    render(<SubtitleRow {...baseProps({ selected: true, onTextChange })} />)
    fireEvent.change(screen.getByPlaceholderText('Subtitle text…'), {
      target: { value: 'New text' },
    })
    expect(onTextChange).toHaveBeenCalledWith('New text')
  })

  it('wires the split / merge / delete actions', () => {
    const onSplit = vi.fn()
    const onMerge = vi.fn()
    const onDelete = vi.fn()
    render(
      <SubtitleRow {...baseProps({ selected: true, onSplit, onMerge, onDelete })} />,
    )
    fireEvent.click(screen.getByTitle('Split at playhead'))
    fireEvent.click(screen.getByTitle('Merge with the next subtitle'))
    fireEvent.click(screen.getByTitle('Delete this subtitle'))
    expect(onSplit).toHaveBeenCalledTimes(1)
    expect(onMerge).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledTimes(1)
  })

  it('disables Merge on the last row', () => {
    render(<SubtitleRow {...baseProps({ selected: true, isLast: true })} />)
    expect(screen.getByTitle('Merge with the next subtitle')).toBeDisabled()
  })

  it('lists issue messages and a tooltip of labels', () => {
    render(
      <SubtitleRow
        {...baseProps({
          selected: true,
          sub: sub({ text: '', start_ms: 3000, end_ms: 3000 }),
          issues: [
            { code: 'EMPTY_TEXT', message: 'Subtitle text is empty.' },
            { code: 'INVALID_TIMESTAMP', message: 'End time must be after start time.' },
          ],
        })}
      />,
    )
    expect(screen.getByText('Subtitle text is empty.')).toBeInTheDocument()
    expect(screen.getByText('End time must be after start time.')).toBeInTheDocument()
    // compact-row warning tooltip summarises the labels
    expect(screen.getByTitle('Empty text, Invalid timestamps')).toBeInTheDocument()
  })
})
