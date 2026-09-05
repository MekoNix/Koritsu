/**
 * Segmented — сегментированный переключатель (`.seg` из макета).
 *
 * Это группа радиокнопок по смыслу, поэтому и по разметке тоже:
 * `role="radiogroup"` — иначе клавиатура обходит его как пять отдельных кнопок,
 * а скринридер не говорит, что выбрано.
 *
 * У области схем есть свой переключатель (`features/diagrams/controls.tsx`):
 * он умеет всплывающую подсказку у сегмента и живёт в колонке параметров. Свести
 * их в один — отдельная работа; здесь общий, тот, что берут настройки и
 * админка.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

import { Icon, type IconName } from './Icon'

export type SegmentedOption<T extends string> = {
  value: T
  label: ReactNode
  icon?: IconName
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = 'md',
  className,
}: {
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  label?: string
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'inline-flex gap-0.5 rounded-btn border border-line bg-surface-2 p-[3px]',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex items-center gap-1.5 whitespace-nowrap rounded-[calc(var(--btn-radius)-2px)] font-medium',
              size === 'sm' ? 'min-h-[24px] px-2.5 text-xs' : 'min-h-[28px] px-3 text-sm',
              active ? 'bg-surface text-ink-strong shadow-1' : 'text-muted hover:text-ink',
            )}
          >
            {option.icon && <Icon name={option.icon} size={14} />}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
