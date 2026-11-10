// App shell: sidebar navigation + worker status + theme toggle.

import { NavLink, Outlet } from 'react-router-dom'
import { Clapperboard, LayoutDashboard, FolderOpen, Moon, Sun } from 'lucide-react'

import { useHealth } from '../api/hooks'
import { useThemeStore } from '../stores/theme'
import { cn } from './ui'

function WorkerDot() {
  const { data, isLoading } = useHealth()
  const online = !isLoading && data?.worker === 'online'
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted">
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          isLoading ? 'bg-warning animate-pulse' : online ? 'bg-success' : 'bg-danger',
        )}
      />
      Worker {isLoading ? '…' : online ? 'online' : 'offline'}
    </div>
  )
}

export default function Layout() {
  const theme = useThemeStore((s) => s.theme)
  const toggle = useThemeStore((s) => s.toggle)

  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface">
        <div className="flex items-center gap-2.5 px-4 py-5">
          <Clapperboard size={22} className="text-accent" />
          <div>
            <p className="text-sm font-semibold leading-tight">Video-to-SRT</p>
            <p className="text-[11px] text-muted">Local AI Studio</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-2">
          {[
            { to: '/', label: 'Dashboard', icon: LayoutDashboard },
            { to: '/projects', label: 'Projects', icon: FolderOpen },
          ].map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent/10 font-medium text-accent'
                    : 'text-muted hover:bg-surface-2 hover:text-text',
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line">
          <WorkerDot />
          <button
            onClick={toggle}
            className="flex w-full items-center gap-2.5 px-4 py-2.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            {theme === 'dark' ? 'Light theme' : 'Dark theme'}
          </button>
        </div>
      </aside>

      <main className="nice-scroll flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
