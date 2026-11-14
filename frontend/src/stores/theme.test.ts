// Store tests: theme toggle + persistence + the documentElement class.

import { beforeEach, describe, expect, it } from 'vitest'

import { useThemeStore } from './theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  useThemeStore.setState({ theme: 'light' })
})

describe('theme store', () => {
  it('defaults to light when the OS prefers light', () => {
    expect(useThemeStore.getState().theme).toBe('light')
  })

  it('toggle() flips the theme, applies the class, and persists', () => {
    useThemeStore.getState().toggle()
    expect(useThemeStore.getState().theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('v2srt-theme')).toBe('dark')

    useThemeStore.getState().toggle()
    expect(useThemeStore.getState().theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('v2srt-theme')).toBe('light')
  })

  it('apply() is idempotent', () => {
    useThemeStore.getState().apply()
    useThemeStore.getState().apply()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('v2srt-theme')).toBe('light')
  })
})
