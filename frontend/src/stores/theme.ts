// Theme store: light/dark with localStorage persistence (§20 UI requirements).

import { create } from 'zustand'

type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  toggle: () => void
  apply: () => void
}

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem('v2srt-theme')
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  toggle: () => {
    set({ theme: get().theme === 'dark' ? 'light' : 'dark' })
    get().apply()
  },
  apply: () => {
    const { theme } = get()
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem('v2srt-theme', theme)
    } catch {
      /* ignore */
    }
  },
}))
