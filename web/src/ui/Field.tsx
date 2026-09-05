/**
 * Field, Input, Textarea — поле ввода с подписью, подсказкой и ошибкой.
 *
 * Ошибка поля — не красная рамка и всё: рамка ничего не говорит человеку,
 * который её не различает. Текст ошибки связан с полем через
 * `aria-describedby` и `aria-invalid`, поэтому его читает и скринридер.
 *
 * `id` придумывается сам (`useId`), если не передан: без связки `label ↔ input`
 * клик по подписи не ставит курсор в поле, а это половина удобства формы.
 */
import {
  forwardRef,
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'

import { cn } from '@/lib/cn'
import { useT } from '@/i18n'

import { Button } from './Button'
import { Icon } from './Icon'

const BASE_INPUT =
  'w-full min-h-[36px] rounded-sm border bg-surface px-3 py-2 font-body text-sm text-ink ' +
  'border-line-strong placeholder:text-muted transition-colors ' +
  'focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent-bg ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

export type FieldProps = {
  label?: ReactNode
  hint?: ReactNode
  /** Текст ошибки. Есть — поле помечено как неверное. */
  error?: string | undefined
  htmlFor?: string
  className?: string
  children: ReactNode
}

export function Field({ label, hint, error, htmlFor, className, children }: FieldProps) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
          {label}
        </label>
      )}
      {children}
      {(error || hint) && (
        <p className={cn('text-xs', error ? 'text-err' : 'text-muted')}>{error ?? hint}</p>
      )}
    </div>
  )
}

export type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: ReactNode
  hint?: ReactNode
  error?: string | undefined
  /** Иконка слева внутри поля. */
  icon?: ReactNode
  wrapperClassName?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, icon, className, wrapperClassName, id, ...rest },
  ref,
) {
  const auto = useId()
  const fieldId = id ?? auto
  const noteId = `${fieldId}-note`
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId} className={wrapperClassName}>
      <div className="relative flex items-center">
        {icon && (
          <span className="pointer-events-none absolute left-2.5 text-muted" aria-hidden="true">
            {icon}
          </span>
        )}
        <input
          ref={ref}
          id={fieldId}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? noteId : undefined}
          className={cn(BASE_INPUT, icon && 'pl-9', error && 'border-err', className)}
          {...rest}
        />
      </div>
    </Field>
  )
})

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: ReactNode
  hint?: ReactNode
  error?: string | undefined
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, id, ...rest },
  ref,
) {
  const auto = useId()
  const fieldId = id ?? auto
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      <textarea
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        className={cn(
          BASE_INPUT,
          'min-h-[88px] resize-y leading-normal',
          error && 'border-err',
          className,
        )}
        {...rest}
      />
    </Field>
  )
})

/**
 * Поле пароля с показом. Показ нужен там, где пароль вводят вслепую и
 * ошибаются: на регистрации и на смене — а на входе тем более, потому что
 * иначе человек третий раз подряд промахивается по раскладке.
 */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, 'type'>>(
  function PasswordInput({ label, hint, error, className, id, ...rest }, ref) {
    const t = useT()
    const [shown, setShown] = useState(false)
    const auto = useId()
    const fieldId = id ?? auto
    return (
      <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
        <div className="relative flex items-center">
          <input
            ref={ref}
            id={fieldId}
            type={shown ? 'text' : 'password'}
            aria-invalid={error ? true : undefined}
            className={cn(BASE_INPUT, 'pr-10', error && 'border-err', className)}
            {...rest}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            iconOnly
            className="absolute right-1"
            aria-label={shown ? t('ui.password.hide') : t('ui.password.show')}
            onClick={() => setShown((v) => !v)}
          >
            <Icon name={shown ? 'eyeOff' : 'eye'} size={16} />
          </Button>
        </div>
      </Field>
    )
  },
)
