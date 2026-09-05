/**
 * Select и Switch — выпадающий список и тумблер.
 *
 * `Select` — родной `<select>` в обёртке `Field`: он умеет то, чего свой список
 * не умеет, — родное окно выбора на телефоне, поиск по первым буквам,
 * клавиатуру без единой строки нашего кода.
 */
import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'

import { cn } from '@/lib/cn'

import { Field } from './Field'

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label?: ReactNode
  hint?: ReactNode
  error?: string | undefined
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, className, id, children, ...rest },
  ref,
) {
  const auto = useId()
  const fieldId = id ?? auto
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      <select
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        className={cn(
          'min-h-[36px] w-full appearance-none rounded-sm border border-line-strong bg-surface py-2 pl-3 pr-8 text-sm text-ink',
          'focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent-bg',
          'disabled:cursor-not-allowed disabled:opacity-50',
          // Треугольник рисуется фоном, как в макете: своя иконка поверх
          // родного списка ловила бы клик и ломала открытие на клавиатуре.
          'bg-[linear-gradient(45deg,transparent_50%,var(--muted)_50%),linear-gradient(135deg,var(--muted)_50%,transparent_50%)]',
          'bg-[length:5px_5px,5px_5px] bg-[position:calc(100%-17px)_50%,calc(100%-12px)_50%] bg-no-repeat',
          error && 'border-err',
          className,
        )}
        {...rest}
      >
        {children}
      </select>
    </Field>
  )
})

/** Переключатель-тумблер (`.switch` из макета). */
export const Switch = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Switch({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        type="checkbox"
        role="switch"
        className={cn(
          'relative m-0 h-[22px] w-[38px] shrink-0 cursor-pointer appearance-none rounded-full bg-line-strong transition-colors',
          'after:absolute after:left-[3px] after:top-[3px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform after:content-[""]',
          'checked:bg-accent checked:after:translate-x-4',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...rest}
      />
    )
  },
)
