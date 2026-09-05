/**
 * Badge — счётчик-кружок (непрочитанные, число задач в очереди).
 *
 * Больше `max` показывается как «99+»: точное число там не нужно, а трёхзначное
 * ломает кружок.
 */
import { cn } from '@/lib/cn'

export type BadgeProps = {
  count: number
  max?: number
  tone?: 'accent' | 'err' | 'muted'
  className?: string
  /** Подпись для скринридера — «непрочитанных: 3», а не голое «3». */
  label?: string
}

const TONES = {
  accent: 'bg-accent text-accent-ink',
  err: 'bg-err text-white',
  muted: 'bg-surface-2 text-muted',
} as const

export function Badge({ count, max = 99, tone = 'accent', className, label }: BadgeProps) {
  if (count <= 0) return null
  return (
    <span
      className={cn(
        'inline-grid h-[18px] min-w-[18px] place-items-center rounded-full px-1.5 text-[11px] font-semibold leading-none',
        TONES[tone],
        className,
      )}
      aria-label={label}
    >
      {count > max ? `${max}+` : count}
    </span>
  )
}
