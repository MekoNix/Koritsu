/**
 * Widget — плитка ленты дашборда.
 *
 * Тонкая обёртка над `Panel` области «Проекты»: у виджета та же поверхность,
 * что у панели проекта, плюс своё место в сетке (`className` с `col-span-*`) и
 * одинаковая высота в ряду (`h-full`). Заводить ради этого второй компонент
 * карточки значило бы иметь две рамки, которые однажды разойдутся на пиксель.
 *
 * Порядок и размеры виджетов **фиксированы** (перетаскивание — потом), поэтому
 * ни ручек, ни режима правки сетки здесь нет.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { Panel } from '@/features/projects/Panel'

export function Widget({
  title,
  note,
  action,
  children,
  className,
  flush,
}: {
  title?: ReactNode
  note?: ReactNode
  action?: ReactNode
  children?: ReactNode
  className?: string
  flush?: boolean
}) {
  return (
    <Panel
      title={title}
      note={note}
      action={action}
      flush={flush}
      className={cn('h-full', className)}
    >
      {children}
    </Panel>
  )
}
