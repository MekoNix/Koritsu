/**
 * Chip и Progress — пилюля состояния и полоса заполнения (`.chip`,
 * `.progress` из макета `11-admin.html`).
 *
 * `Badge` рядом — не то же самое: он счётчик-кружок на колокольчике, а это
 * подпись состояния строкой («работает», «отозван») и доля от целого.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

/** Пилюля состояния. */
export function Chip({
  tone = 'muted',
  children,
  className,
}: {
  tone?: 'muted' | 'ok' | 'warn' | 'err' | 'info' | 'accent'
  children: ReactNode
  className?: string
}) {
  const TONES = {
    muted: 'text-muted border-line bg-surface',
    ok: 'text-ok border-[color-mix(in_srgb,var(--ok)_45%,transparent)] bg-ok-bg',
    warn: 'text-warn border-[color-mix(in_srgb,var(--warn)_45%,transparent)] bg-warn-bg',
    err: 'text-err border-[color-mix(in_srgb,var(--err)_45%,transparent)] bg-err-bg',
    info: 'text-info border-[color-mix(in_srgb,var(--info)_45%,transparent)] bg-info-bg',
    accent: 'text-accent border-[color-mix(in_srgb,var(--accent)_45%,transparent)] bg-accent-bg',
  } as const
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 font-mono text-xs leading-normal',
        TONES[tone],
        className,
      )}
    >
      <i aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
      {children}
    </span>
  )
}

/** Полоса заполнения. */
export function Progress({
  value,
  tone = 'accent',
  className,
  label,
}: {
  /** Доля от 0 до 1; больше единицы обрезается. */
  value: number
  tone?: 'accent' | 'ok' | 'warn' | 'err'
  className?: string
  label?: string
}) {
  const percent = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100
  const FILL = { accent: 'bg-accent', ok: 'bg-ok', warn: 'bg-warn', err: 'bg-err' } as const
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-surface-2', className)}
    >
      <i className={cn('block h-full rounded-full', FILL[tone])} style={{ width: `${percent}%` }} />
    </div>
  )
}
