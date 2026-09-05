/**
 * Widget — плитка ленты дашборда.
 *
 * Тонкая обёртка над `Panel` области «Проекты»: у виджета та же поверхность,
 * что у панели проекта, плюс своё место в сетке (`className` с `col-span-*`) и
 * одинаковая высота в ряду (`h-full`). Заводить ради этого второй компонент
 * карточки значило бы иметь две рамки, которые однажды разойдутся на пиксель.
 *
 * Своей ширины в сетке виджет не знает: её несёт клетка, в которую он вложен
 * (`order.ts`, `DashboardGrid`). Иначе переставленная рукой клетка меняла бы
 * место, но не размер.
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
