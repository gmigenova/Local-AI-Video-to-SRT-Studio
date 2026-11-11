// App shell: desktop sidebar navigation + mobile top bar with a bottom
// tab bar (native-app style). Worker status + theme toggle everywhere.

import { NavLink, Outlet } from 'react-router-dom'
import { Clapperboard, LayoutDashboard, FolderOpen, Moon, Sun } from 'lucide-react'

import { useHealth } from '../api/hooks'
import { useThemeStore } from '../stores/theme'
import { cn } from './ui'

function WorkerDot({ withLabel = true }: { withLabel?: boolean }) {
  const { data, isLoading } = useHealth()
  const online = !isLoading && data?.worker === 'online'
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          isLoading ? 'bg-warning animate-pulse' : online ? 'bg-success' : 'bg-danger',
        )}
      />
      {withLabel ? (
        <span>Worker {isLoading ? '…' : online ? 'online' : 'offline'}</span>
      ) : null}
    </div>
  )
}

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/projects', label: 'Projects', icon: FolderOpen },
]

export default function Layout() {
  const theme = useThemeStore((s) => s.theme)
  const toggle = useThemeStore((s) => s.toggle)

  return (
    <div className="flex h-dvh flex-col md:flex-row">
      {/* mobile top bar */}
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3 md:hidden">
        <div className="flex items-center gap-2.5">
          <Clapperboard size={20} className="text-accent" />
          <div>
            <p className="text-sm font-semibold leading-tight">Video-to-SRT</p>
            <p className="text-[11px] leading-tight text-muted">Local AI Studio</p>
          </div>
        </div>
        <WorkerDot withLabel={false} />
      </header>

      {/* desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex items-center gap-2.5 px-4 py-5">
          <Clapperboard size={22} className="text-accent" />
          <div>
            <p className="text-sm font-semibold leading-tight">Video-to-SRT</p>
            <p className="text-[11px] text-muted">Local AI Studio</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
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
        <div className="mx-auto max-w-6xl px-4 pb-28 pt-4 md:px-8 md:pb-8 md:pt-8">
          <Outlet />
        </div>
      </main>

      {/* mobile bottom tab bar (safe-area aware) */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-surface/95 backdrop-blur md:hidden">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex flex-1 flex-col items-center gap-0.5 pb-[calc(env(safe-area-inset-bottom)+0.4rem)] pt-2.5 text-[11px] transition-colors',
                isActive ? 'text-accent' : 'text-muted',
              )
            }
          >
            <Icon size={22} />
            {label}
          </NavLink>
        ))}
        <button
          onClick={toggle}
          className="flex flex-1 flex-col items-center gap-0.5 pb-[calc(env(safe-area-inset-bottom)+0.4rem)] pt-2.5 text-[11px] text-muted transition-colors active:text-accent"
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? <Sun size={22} /> : <Moon size={22} />}
          Theme
        </button>
      </nav>
    </div>
  )
}
