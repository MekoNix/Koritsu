/**
 * Button — кнопка во всех видах из макета.
 *
 * Виды: `primary` (основное действие), `secondary` (поверхность с границей),
 * `ghost` (без фона), `danger` (удаление), `agent` (всё, что делает агент —
 * цвет `--agent` обязан отличаться от `--accent`, это правило спецификации).
 *
 * `loading` не подменяет содержимое спиннером, а гасит текст и рисует кружок
 * поверх: иначе кнопка меняет ширину в момент нажатия и уезжает из-под курсора.
 *
 * `asChild` (Radix Slot) — когда кнопкой должна быть ссылка роутера: вид
 * кнопки, семантика ссылки, работающий Ctrl+клик.
 */
import { Slot } from '@radix-ui/react-slot'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'agent'
export type ButtonSize = 'sm' | 'md' | 'lg'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-ink border-transparent hover:brightness-110',
  secondary: 'bg-surface text-ink border-line-strong shadow-1 hover:bg-surface-2',
  ghost: 'bg-transparent text-ink border-transparent hover:bg-surface-2',
  danger: 'bg-err text-white border-transparent hover:brightness-110',
  agent: 'bg-agent-bg text-agent border-transparent hover:brightness-110',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'min-h-[30px] px-3 text-xs gap-1.5',
  md: 'min-h-[36px] px-4 text-sm gap-2',
  lg: 'min-h-[44px] px-5 text-md gap-2',
}

const ICON_SIZES: Record<ButtonSize, string> = {
  sm: 'w-[30px] min-w-[30px] px-0',
  md: 'w-[36px] min-w-[36px] px-0',
  lg: 'w-[44px] min-w-[44px] px-0',
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Только иконка: квадрат вместо прямоугольника. Требует `aria-label`. */
  iconOnly?: boolean
  loading?: boolean
  asChild?: boolean
  children?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    iconOnly = false,
    loading = false,
    asChild = false,
    className,
    disabled,
    children,
    ...rest
  },
  ref,
) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      ref={ref}
      // `aria-busy` — чтобы «идёт работа» слышал и тот, кто кружок не видит.
      aria-busy={loading || undefined}
      disabled={asChild ? undefined : disabled || loading}
      className={cn(
        'relative inline-flex items-center justify-center whitespace-nowrap rounded-btn border font-body font-semibold leading-tight',
        'transition-[background-color,filter] duration-150',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        'disabled:cursor-not-allowed disabled:opacity-45 disabled:filter-none',
        VARIANTS[variant],
        SIZES[size],
        iconOnly && ICON_SIZES[size],
        loading && 'text-transparent',
        className,
      )}
      {...rest}
    >
      {/*
        Со `Slot` (`asChild`) детей обязан быть ровно один: Radix зовёт
        `Children.only`, а `{loading && …}` подставляет вторым ребёнком `false`
        даже когда загрузки нет — и любая кнопка-ссылка падала бы на первом же
        рендере. Поэтому кружок добавляется только настоящей кнопке; ссылке он
        и не нужен: она никуда не «грузится», а ведёт.
      */}
      {asChild ? (
        children
      ) : (
        <>
          {children}
          {loading && (
            <span
              aria-hidden="true"
              className="absolute h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent text-ink"
            />
          )}
        </>
      )}
    </Comp>
  )
})
