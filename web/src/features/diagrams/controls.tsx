/**
 * controls — мелочи разметки экранов схем: переключатель-сегмент, панель,
 * список замечаний разбора.
 *
 * Лежат здесь, а не в `ui/`, намеренно: общий набор компонентов делает агент A,
 * и всё, что понадобилось одной области, обязано жить в этой области, пока не
 * понадобится второй. Переезд отсюда в `ui/` — правка на пять строк, обратный
 * путь стоит дороже.
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon } from '@/ui'

import type { Notice } from './types'

export type SegmentedOption<T extends string> = {
  value: T
  label: string
  title?: string
  disabled?: boolean
}

/**
 * Переключатель из макета: несколько значений в ряд, выбрано одно.
 *
 * `role="radiogroup"` — потому что это и есть выбор одного из нескольких:
 * группа кнопок без роли читается вслух как набор несвязанных действий.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string
  value: T
  options: SegmentedOption<T>[]
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'inline-flex min-w-0 flex-wrap gap-1 rounded-sm border border-line-strong bg-surface-2 p-1',
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
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              'min-h-[28px] rounded-sm px-2.5 text-xs font-semibold leading-tight transition-colors',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent',
              'disabled:cursor-not-allowed disabled:opacity-45',
              active ? 'bg-surface text-ink-strong shadow-1' : 'text-muted hover:text-ink',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/** Подписанный блок параметра. Подпись — не `<label>`: под ней группа, не поле. */
export function ControlBlock({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <span className="text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  )
}

/** Сколько замечаний показываем сразу: остальные — числом. */
const ВИДНО = 4

/**
 * Замечания разбора («в схему не вошло: goto case»). Не ошибка: схема
 * построена, и прятать их незачем, но и кричать о них нечем — предупреждение.
 */
export function Notices({ notices }: { notices: Notice[] }) {
  const t = useT()
  if (!notices.length) return null
  const видимые = notices.slice(0, ВИДНО)
  const остальные = notices.length - видимые.length
  return (
    <div className="flex flex-col gap-1 rounded-sm border border-line bg-warn-bg p-s3">
      <div className="flex items-center gap-s2 text-xs font-semibold text-warn">
        <Icon name="warning" size={14} />
        {t('diagrams.work.notices')}
      </div>
      <ul className="flex flex-col gap-0.5 text-xs text-ink">
        {видимые.map((notice, i) => (
          <li key={`${notice.code}-${i}`}>
            {notice.message}
            {notice.line ? ` · ${notice.file ?? ''}:${notice.line}` : ''}
          </li>
        ))}
      </ul>
      {остальные > 0 && (
        <span className="text-xs text-muted">
          {t('diagrams.work.noticesMore', { n: остальные })}
        </span>
      )}
    </div>
  )
}
