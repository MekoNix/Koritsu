/**
 * states — обязательные состояния экрана: скелетон, пусто, ошибка, нет прав.
 *
 * Они требуются от каждого экрана, и требование это не про
 * красоту: экран без пустого состояния встречает нового человека белым полем,
 * а без состояния ошибки — вечной «загрузкой». Поэтому они лежат готовыми
 * компонентами, а не переписываются в каждой области заново.
 *
 * Скелетон, а не спиннер, — там, где структура известна заранее: спиннер
 * сообщает «ждите», скелетон — «вот что здесь будет», и второе короче на одну
 * догадку.
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { errorText } from '@/api/errors'
import { cn } from '@/lib/cn'

import { Button } from './Button'
import { Icon, type IconName } from './Icon'

/** Полоса-заглушка. Ширина и высота — через className. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'h-3.5 animate-shimmer rounded-sm',
        'bg-[linear-gradient(90deg,var(--surface-2)_25%,var(--surface-3)_50%,var(--surface-2)_75%)] bg-[length:200%_100%]',
        className,
      )}
    />
  )
}

/** Несколько строк скелетона — самый частый случай. */
export function SkeletonLines({ count = 3, className }: { count?: number; className?: string }) {
  const t = useT()
  return (
    <div
      className={cn('flex flex-col gap-s2', className)}
      role="status"
      aria-label={t('ui.skeleton.label')}
    >
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className={i === count - 1 ? 'w-2/5' : 'w-full'} />
      ))}
    </div>
  )
}

export function Spinner({ className, size = 20 }: { className?: string; size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className={cn(
        'inline-block shrink-0 animate-spin rounded-full border-2 border-line-strong border-t-accent',
        className,
      )}
    />
  )
}

export type EmptyStateProps = {
  icon?: IconName
  title?: ReactNode
  text?: ReactNode
  /** Приглашение к действию: без него пустое состояние — просто пустое место. */
  action?: ReactNode
  compact?: boolean
  className?: string
}

export function EmptyState({
  icon = 'inbox',
  title,
  text,
  action,
  compact = false,
  className,
}: EmptyStateProps) {
  const t = useT()
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-s2 text-center text-muted',
        compact ? 'px-s5 py-s4' : 'px-s5 py-s8',
        className,
      )}
    >
      <Icon name={icon} size={compact ? 28 : 40} className="text-line-strong" />
      <div className="font-display text-lg font-semibold text-ink-strong">
        {title ?? t('ui.empty.title')}
      </div>
      {text && <p className="max-w-[40ch] text-sm">{text}</p>}
      {action && <div className="mt-s2">{action}</div>}
    </div>
  )
}

export type ErrorStateProps = {
  /** Что упало: `ApiError`, обычная ошибка или готовый текст. */
  error?: unknown
  title?: ReactNode
  onRetry?: () => void
  className?: string
}

/**
 * Экран ошибки. Текст берётся из `errorText()` — то есть русский по коду
 * службы, с английским сообщением как запасным. Второго перевода здесь нет.
 */
export function ErrorState({ error, title, onRetry, className }: ErrorStateProps) {
  const t = useT()
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center gap-s3 rounded-md border border-dashed p-s8 text-center',
        // Прозрачность через `/40` тут не работает: цвет темы — готовое
        // значение, а не тройка каналов. Приглушение даёт `color-mix`.
        'border-[color-mix(in_srgb,var(--err)_40%,transparent)] bg-err-bg',
        className,
      )}
    >
      <Icon name="error" size={36} className="text-err" />
      <div className="font-display text-lg font-semibold text-ink-strong">
        {title ?? t('ui.error.title')}
      </div>
      {error !== undefined && <p className="max-w-[48ch] text-sm text-ink">{errorText(error)}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          <Icon name="refresh" size={16} />
          {t('ui.error.retry')}
        </Button>
      )}
    </div>
  )
}

/** Отсутствие прав — отдельное состояние, а не ошибка: чинить человеку нечего. */
export function ForbiddenState({ className }: { className?: string }) {
  const t = useT()
  return (
    <EmptyState
      icon="user"
      title={t('common.state.forbidden')}
      text={t('common.state.forbiddenHint')}
      className={className}
    />
  )
}
