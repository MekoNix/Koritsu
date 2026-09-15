/**
 * ProblemsTable — проблемы разбора файла набора.
 *
 * Проблема называет место, где её чинить: карточку и поле по пути JSON
 * (`cards[12].a` — «карточка 13, поле «ответ»»), у битого JSON — строку и столбец,
 * у CSV/TSV — строку таблицы. Проблема всего файла — без места.
 *
 * На компьютере — таблица с закреплённой шапкой и своей прокруткой, чтобы пятьсот
 * строк не растягивали страницу; на телефоне — список «карточка 13, поле «ответ»» над
 * текстом проблемы, без горизонтальной прокрутки. Показываются первые `limit`
 * проблем по порядку файла, остальные — числом: чинить файл всё равно начинают сверху.
 */
import { useMemo } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { useIsPhone } from '../hooks/useIsPhone'
import type { Problem } from '../types'
import { problemCard, problemPlace } from './problemPlace'

export type ProblemsTableProps = {
  problems: Problem[]
  limit?: number
  className?: string
}

/** Порядок файла: проблемы всего файла первыми, затем по карточке, затем по строке. */
function order(p: Problem): [number, number] {
  return [problemCard(p) ?? -1, p.line ?? -1]
}

export function ProblemsTable({ problems, limit = 200, className }: ProblemsTableProps) {
  const t = useT()
  const isPhone = useIsPhone()
  const sorted = useMemo(
    () =>
      [...problems].sort((a, b) => {
        const [ac, al] = order(a)
        const [bc, bl] = order(b)
        return ac - bc || al - bl
      }),
    [problems],
  )
  const shown = sorted.slice(0, limit)
  const rest = sorted.length - shown.length

  if (!problems.length) return null

  const ещё = rest > 0 && <p className="m-0 text-xs text-muted">{t('cards.common.problem.more', { n: rest })}</p>

  if (isPhone) {
    return (
      <div className={cn('flex flex-col gap-s2', className)}>
        <ul className="m-0 flex list-none flex-col divide-y divide-line rounded-md border border-line bg-surface p-0">
          {shown.map((p, i) => (
            <li key={i} className="flex flex-col gap-0.5 px-s3 py-s2">
              <span className="break-words text-xs text-muted">{problemPlace(t, p)}</span>
              <span className="break-words text-sm text-ink">{p.text}</span>
            </li>
          ))}
        </ul>
        {ещё}
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col gap-s2', className)}>
      <div className="max-h-[420px] overflow-auto rounded-md border border-line bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-surface-2">
            <tr>
              <th scope="col" className="w-[36%] px-s3 py-s2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
                {t('cards.common.problem.placeHead')}
              </th>
              <th scope="col" className="px-s3 py-s2 text-left text-xs font-semibold uppercase tracking-wider text-muted">
                {t('cards.common.problem.textHead')}
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((p, i) => {
              const place = problemPlace(t, p)
              const whole = problemCard(p) === null && !p.path && p.line === null
              return (
                <tr key={i} className="border-t border-line align-top">
                  <td className="break-words px-s3 py-s2 text-xs text-muted">
                    {whole ? <span className="font-semibold text-err">{place}</span> : place}
                    {p.path && <span className="mt-0.5 block break-all font-mono text-[11px]">{p.path}</span>}
                  </td>
                  <td className="break-words px-s3 py-s2 text-ink">
                    {p.text}
                    <span className="ml-s2 font-mono text-xs text-muted">{p.code}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {ещё}
    </div>
  )
}
