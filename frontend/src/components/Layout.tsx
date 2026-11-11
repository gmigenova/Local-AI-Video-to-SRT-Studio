// App shell: collapsible desktop sidebar navigation + mobile top bar with a
// bottom tab bar (native-app style). Worker status + theme toggle everywhere.
// The collapse state persists per viewer (localStorage, stores/sidebar.ts).

import { NavLink, Outlet } from 'react-router-dom'
import {
  Clapperboard,
  LayoutDashboard,
  FolderOpen,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
} from 'lucide-react'

import { useHealth } from '../api/hooks'
import { useSidebarStore } from '../stores/sidebar'
import { useThemeStore } from '../stores/theme'
import { cn } from './ui'

function WorkerDot({ withLabel = true }: { withLabel?: boolean }) {
  const { data, isLoading } = useHealth()
  const online = !isLoading && data?.worker === 'online'
  const state = isLoading ? '…' : online ? 'online' : 'offline'
  return (
    <div
      className={cn('flex items-center gap-2 text-xs text-muted', !withLabel && 'justify-center')}
      title={withLabel ? undefined : `Worker ${state}`}
    >
      <span
        className={cn(
          'h-2 w-2 shrink-0 rounded-full',
          isLoading ? 'bg-warning animate-pulse' : online ? 'bg-success' : 'bg-danger',
        )}
      />
      {withLabel ? <span>Worker {state}</span> : null}
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
  const collapsed = useSidebarStore((s) => s.collapsed)
  const toggleSidebar = useSidebarStore((s) => s.toggle)

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

      {/* desktop sidebar (collapsible: icons only when collapsed) */}
      <aside
        className={cn(
          'hidden shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200 md:flex',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2.5 py-5',
            collapsed ? 'justify-center px-2' : 'px-4',
          )}
        >
          <Clapperboard size={22} className="shrink-0 text-accent" />
          {collapsed ? null : (
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-tight">Video-to-SRT</p>
              <p className="text-[11px] text-muted">Local AI Studio</p>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-1 px-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={collapsed ? label : undefined}
              aria-label={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'flex items-center rounded-lg py-2 text-sm transition-colors',
                  collapsed ? 'justify-center px-2' : 'gap-2.5 px-3',
                  isActive
                    ? 'bg-accent/10 font-medium text-accent'
                    : 'text-muted hover:bg-surface-2 hover:text-text',
                )
              }
            >
              <Icon size={16} className="shrink-0" />
              {collapsed ? null : label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line">
          <div className={cn('py-2.5', collapsed ? 'px-2' : 'px-4')}>
            <WorkerDot withLabel={!collapsed} />
          </div>
          <button
            onClick={toggle}
            title={collapsed ? (theme === 'dark' ? 'Light theme' : 'Dark theme') : undefined}
            aria-label={collapsed ? 'Toggle theme' : undefined}
            className={cn(
              'flex w-full items-center py-2.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-text',
              collapsed ? 'justify-center px-2' : 'gap-2.5 px-4',
            )}
          >
            {theme === 'dark' ? <Sun size={16} className="shrink-0" /> : <Moon size={16} className="shrink-0" />}
            {collapsed ? null : theme === 'dark' ? 'Light theme' : 'Dark theme'}
          </button>
          <button
            onClick={toggleSidebar}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn(
              'flex w-full items-center border-t border-line py-2.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-text',
              collapsed ? 'justify-center px-2' : 'gap-2.5 px-4',
            )}
          >
            {collapsed ? (
              <PanelLeftOpen size={16} className="shrink-0" />
            ) : (
              <>
                <PanelLeftClose size={16} className="shrink-0" />
                Collapse
              </>
            )}
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
