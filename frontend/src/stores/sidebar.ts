// Sidebar collapse state: persisted per viewer (a convenience, not data).

import { create } from 'zustand'

interface SidebarState {
  collapsed: boolean
  toggle: () => void
  setCollapsed: (collapsed: boolean) => void
}

function readStored(): boolean | null {
  try {
    const stored = localStorage.getItem('v2srt-sidebar-collapsed')
    if (stored === 'true') return true
    if (stored === 'false') return false
  } catch {
    /* storage unavailable */
  }
  return null
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  collapsed: readStored() ?? false,
  toggle: () => get().setCollapsed(!get().collapsed),
  setCollapsed: (collapsed) => {
    set({ collapsed })
    try {
      localStorage.setItem('v2srt-sidebar-collapsed', String(collapsed))
    } catch {
      /* ignore */
    }
  },
}))
