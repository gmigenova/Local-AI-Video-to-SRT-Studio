// Minimal UI primitives (shadcn-style, hand-rolled to stay dependency-light).

import { useEffect, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { ChevronDown, X } from 'lucide-react'

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

export function Button({
  variant = 'primary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const styles: Record<ButtonVariant, string> = {
    primary: 'bg-accent text-accent-text hover:bg-accent-hover',
    secondary: 'bg-surface-2 text-text hover:bg-line',
    danger: 'bg-transparent text-danger border border-danger/40 hover:bg-danger/10',
    ghost: 'bg-transparent text-muted hover:text-text hover:bg-surface-2',
  }
  return (
    <button
      className={cn(
        'inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium',
        'transition-[colors,transform] duration-100 active:scale-[0.98]',
        'disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
        styles[variant],
        className,
      )}
      {...props}
    />
  )
}

/** Click-triggered dropdown menu (closes on outside click / Escape / item click). */
export function DropdownMenu({
  label,
  title,
  variant = 'primary',
  children,
}: {
  label: ReactNode
  title?: string
  variant?: ButtonVariant
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={wrapperRef} className="relative">
      <Button
        variant={variant}
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
        <ChevronDown
          size={15}
          className={cn('shrink-0 transition-transform duration-150', open && 'rotate-180')}
        />
      </Button>
      {open ? (
        <div
          role="menu"
          onClick={() => setOpen(false)}
          className="animate-scale-in absolute right-0 z-40 mt-1.5 min-w-56 origin-top-right rounded-lg border border-line bg-surface py-1 shadow-raised"
        >
          {children}
        </div>
      ) : null}
    </div>
  )
}

export function DropdownItem({
  icon,
  hint,
  href,
  download,
  onClick,
  children,
}: {
  icon?: ReactNode
  hint?: string
  href?: string
  download?: boolean | string
  onClick?: () => void
  children: ReactNode
}) {
  const className =
    'flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-surface-2'
  const content = (
    <>
      {icon ? <span className="shrink-0 text-muted">{icon}</span> : null}
      <span className="flex-1">{children}</span>
      {hint ? <span className="font-mono text-[11px] text-muted">{hint}</span> : null}
    </>
  )
  if (href !== undefined) {
    return (
      <a href={href} download={download} role="menuitem" className={className}>
        {content}
      </a>
    )
  }
  return (
    <button type="button" onClick={onClick} role="menuitem" className={className}>
      {content}
    </button>
  )
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-xl border border-line bg-surface shadow-card', className)}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}) {
  const tones = {
    neutral: 'bg-surface-2 text-muted',
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/10 text-warning',
    danger: 'bg-danger/10 text-danger',
    info: 'bg-accent/10 text-accent',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        tones[tone],
      )}
    >
      {children}
    </span>
  )
}

export function Progress({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value))
  const done = pct >= 100
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
      <div
        className={cn(
          'h-full rounded-full bg-accent transition-[width] duration-500',
          !done && 'progress-sheen',
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted/80">{hint}</span> : null}
    </label>
  )
}

export const inputClass =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-text ' +
  'outline-none transition-colors placeholder:text-muted/60 focus:border-accent'

export function Modal({
  open,
  title,
  onClose,
  children,
  wide = false,
  hideClose = false,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
  /** hide the header X (e.g. while an in-flight state owns the dialog) */
  hideClose?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      {/* mobile: bottom sheet; desktop: centered dialog */}
      <div
        className={cn(
          'animate-slide-up nice-scroll relative z-10 max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl border border-line bg-surface pb-[calc(env(safe-area-inset-bottom)+0.75rem)] shadow-raised sm:max-h-[85vh] sm:animate-scale-in sm:rounded-xl sm:pb-0',
          wide ? 'sm:max-w-2xl' : 'sm:max-w-md',
        )}
      >
        {/* drag handle (mobile only) */}
        <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-line sm:hidden" />
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-5 py-3.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {hideClose ? null : (
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-text"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          )}
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent',
        className,
      )}
    />
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-line px-6 py-14 text-center">
      <div className="text-muted">{icon}</div>
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-xs text-muted">{description}</p>
      </div>
      {action}
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, 'neutral' | 'success' | 'warning' | 'danger' | 'info'> = {
    queued: 'neutral',
    validating: 'info',
    extracting_audio: 'info',
    transcribing: 'info',
    processing_subtitles: 'info',
    completed: 'success',
    failed: 'danger',
    cancelling: 'warning',
    cancelled: 'warning',
  }
  return <Badge tone={map[status] ?? 'neutral'}>{status.replace(/_/g, ' ')}</Badge>
}
