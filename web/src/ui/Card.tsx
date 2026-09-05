/**
 * Card и Row — карточка раздела и строка «подпись — значение».
 *
 * Заведены ночью 1 в области настроек (`features/settings/parts.tsx`), потому
 * что над сайтом работали пятеро сразу и два агента, одновременно заводящие
 * `ui/Card.tsx`, затёрли бы друг друга. На сведении переехали сюда: карточку
 * берут и настройки, и админка, а это ровно то определение общего компонента,
 * которое написано в `ui/README.md`.
 *
 * Вид — из макетов `10-auth-settings.html` и `11-admin.html`
 * (`assets/base.css`: `.card`), переписанный на переменные тем: ни одного
 * своего цвета.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

/** Карточка раздела: заголовок, пояснение, содержимое. */
export function Card({
  title,
  desc,
  action,
  tone = 'normal',
  className,
  children,
}: {
  title?: ReactNode
  desc?: ReactNode
  /** Кнопки в правом верхнем углу карточки. */
  action?: ReactNode
  tone?: 'normal' | 'danger'
  className?: string
  children?: ReactNode
}) {
  return (
    <section
      className={cn(
        'flex min-w-0 flex-col gap-s3 rounded-md border bg-surface p-s4 shadow-1 backdrop-blur-theme',
        tone === 'danger'
          ? 'border-[color-mix(in_srgb,var(--err)_45%,var(--line))]'
          : 'border-line',
        className,
      )}
    >
      {(title || action) && (
        <div className="flex items-start justify-between gap-s3">
          <div className="min-w-0">
            {title && (
              <h2
                className={cn(
                  'font-display text-md font-semibold leading-tight',
                  tone === 'danger' ? 'text-err' : 'text-ink-strong',
                )}
              >
                {title}
              </h2>
            )}
            {desc && <p className="mt-1 text-sm text-muted">{desc}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-s2">{action}</div>}
        </div>
      )}
      {!title && desc && <p className="text-sm text-muted">{desc}</p>}
      {children}
    </section>
  )
}

/** Строка «подпись — значение» для карточек, где менять нечего. */
export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-s2 border-b border-line py-1.5 last:border-b-0">
      <span className="text-sm text-muted">{label}</span>
      <span className="min-w-0 break-words text-sm text-ink-strong">{children}</span>
    </div>
  )
}
