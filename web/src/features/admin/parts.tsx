/**
 * parts — две мелочи, общие для таблиц админки: заголовок-сортировщик и кнопка
 * выгрузки.
 *
 * Отдельным файлом, потому что их берут три вкладки. В `ui/` они не поехали
 * намеренно: сортировка тут своя (список приходит целиком и сортируется на
 * месте), и общий компонент таблицы, годный всему сайту, — это работа, которую
 * стоит делать, когда таблиц станет больше трёх.
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { Button, Icon } from '@/ui'
import { cn } from '@/lib/cn'

import { downloadCsv, toCsv, type SortState } from './table'

/**
 * Заголовок столбца, по которому можно сортировать.
 *
 * `aria-sort` — не украшение: без него скринридер объявляет кнопку, но не
 * говорит, что список ею переставлен и в какую сторону. Стрелка показывается
 * только у выбранного столбца — шесть стрелок в шапке читаются как
 * «сортировано по всему сразу».
 */
export function SortHeader<C extends string>({
  col,
  state,
  onSort,
  className,
  children,
}: {
  col: C
  state: SortState<C>
  onSort: (col: C) => void
  className?: string
  children: ReactNode
}) {
  const t = useT()
  const выбран = state?.col === col
  return (
    <th
      scope="col"
      aria-sort={выбран ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cn(
        'sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-surface p-0 text-left',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onSort(col)}
        title={t('admin.sort')}
        className={cn(
          'flex w-full items-center gap-1 px-3 py-2 text-xs font-semibold uppercase tracking-wide',
          className?.includes('text-right') && 'justify-end',
          выбран ? 'text-ink-strong' : 'text-muted hover:text-ink',
        )}
      >
        {children}
        <Icon
          name={выбран && state.dir === 'asc' ? 'chevronUp' : 'chevronDown'}
          size={14}
          className={выбран ? undefined : 'opacity-0'}
        />
      </button>
    </th>
  )
}

/**
 * Кнопка «выгрузить CSV». Считается в браузере из того, что уже показано:
 * маршрута выгрузки у службы нет, и заводить его ради файла, который целиком
 * лежит в памяти вкладки, незачем.
 */
export function CsvButton({
  name,
  headers,
  rows,
  disabled,
}: {
  /** Имя файла вместе с `.csv`. */
  name: string
  headers: readonly string[]
  rows: () => readonly unknown[][]
  disabled?: boolean
}) {
  const t = useT()
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={disabled}
      onClick={() => downloadCsv(name, toCsv(headers, rows()))}
    >
      <Icon name="download" size={16} />
      {t('admin.csv')}
    </Button>
  )
}
