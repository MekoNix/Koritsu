/**
 * Panel — карточка-поверхность: рамка, фон, заголовок и место для действия.
 *
 * Лежит в области B, а не в `src/ui`: общий набор компонентов ведёт агент A, и
 * дописывать туда файлы посреди ночи значит толкаться в чужом дереве. Из этой
 * карточки собраны и виджеты дашборда, и панели страницы проекта — вид у них
 * один и тот же, и второй раз его описывать незачем.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

export type PanelProps = {
  title?: ReactNode
  /** Приписка рядом с заголовком — мелким, приглушённым. */
  note?: ReactNode
  /** Кнопка или ссылка в правом верхнем углу. */
  action?: ReactNode
  children?: ReactNode
  className?: string
  /** Тело без внутренних отступов: список строк рисует их сам. */
  flush?: boolean
}

export function Panel({ title, note, action, children, className, flush = false }: PanelProps) {
  // Без шапки отступ нужен со всех сторон, с шапкой — только снизу и по бокам:
  // сверху его уже дала сама шапка.
  const шапка = Boolean(title || action)
  const отступы = flush ? '' : шапка ? 'px-s4 pb-s4' : 'p-s4'
  return (
    <section
      className={cn(
        'flex min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface shadow-1',
        className,
      )}
    >
      {шапка && (
        <header className="flex min-w-0 items-center gap-s2 px-s4 py-s3">
          <h2 className="min-w-0 truncate font-display text-md font-semibold text-ink-strong">
            {title}
          </h2>
          {note && <span className="min-w-0 truncate text-xs text-muted">{note}</span>}
          {action && <div className="ml-auto flex shrink-0 items-center gap-s2">{action}</div>}
        </header>
      )}
      <div className={cn('min-w-0 flex-1', отступы)}>{children}</div>
    </section>
  )
}
