// Store tests: sidebar collapse persistence.

import { beforeEach, describe, expect, it } from 'vitest'

import { useSidebarStore } from './sidebar'

beforeEach(() => {
  localStorage.clear()
  useSidebarStore.setState({ collapsed: false })
})

describe('sidebar store', () => {
  it('defaults to expanded', () => {
    expect(useSidebarStore.getState().collapsed).toBe(false)
  })

  it('toggle() flips and persists', () => {
    useSidebarStore.getState().toggle()
    expect(useSidebarStore.getState().collapsed).toBe(true)
    expect(localStorage.getItem('v2srt-sidebar-collapsed')).toBe('true')

    useSidebarStore.getState().toggle()
    expect(useSidebarStore.getState().collapsed).toBe(false)
    expect(localStorage.getItem('v2srt-sidebar-collapsed')).toBe('false')
  })

  it('setCollapsed() persists an explicit value', () => {
    useSidebarStore.getState().setCollapsed(true)
    expect(localStorage.getItem('v2srt-sidebar-collapsed')).toBe('true')
  })
})
