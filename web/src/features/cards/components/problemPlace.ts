/**
 * problemPlace — где в файле набора проблема, словами человека.
 *
 * Служба называет место путём JSON (`cards[12].a`) и номером карточки с нуля; у
 * битого JSON — строкой и столбцом. Человеку это «карточка 13, поле «ответ»» и
 * «строка 3, столбец 14». Поля карточки и корня файла, которые знает формат,
 * названы по-русски; прочие показываются путём как есть.
 */
import type { useT } from '@/i18n'

import type { Problem } from '../types'

type T = ReturnType<typeof useT>

/** Поля карточки, у которых есть название. */
const CARD_FIELDS = new Set(['q', 'a', 'note', 'topic', 'id'])
/** Поля корня файла, у которых есть название. */
const FILE_FIELDS = new Set(['format', 'version', 'title', 'description', 'language', 'defaults', 'cards'])

/** Путь JSON → номер карточки (с нуля) и остаток пути внутри неё или корня. */
export function splitPath(path: string | null | undefined): { card: number | null; field: string | null } {
  if (!path) return { card: null, field: null }
  const m = /^cards\[(\d+)\](?:\.(.+))?$/.exec(path)
  if (m) return { card: Number(m[1]), field: m[2] ?? null }
  return { card: null, field: path }
}

/** Название поля: `a` → «ответ», `defaults.order` → «defaults.order». */
export function fieldName(t: T, field: string, inCard: boolean): string {
  const known = inCard ? CARD_FIELDS : FILE_FIELDS
  return known.has(field)
    ? t(`cards.common.problem.fields.${inCard ? 'card' : 'file'}.${field}`)
    : field
}

/** «поле «ответ»» по пути проблемы или `null`, если поля в пути нет. */
export function problemField(t: T, p: Pick<Problem, 'path'>): string | null {
  const { card, field } = splitPath(p.path)
  if (!field) return null
  return t('cards.common.problem.field', { name: fieldName(t, field, card !== null) })
}

/** Номер карточки проблемы с нуля: из `card`, а без него — из пути. */
export function problemCard(p: Pick<Problem, 'card' | 'path'>): number | null {
  if (typeof p.card === 'number') return p.card
  return splitPath(p.path).card
}

/** Место проблемы целиком: «карточка 13, поле «ответ»», «строка 3, столбец 14», «весь файл». */
export function problemPlace(t: T, p: Problem): string {
  const parts: string[] = []
  const card = problemCard(p)
  if (card !== null) parts.push(t('cards.common.problem.card', { n: card + 1 }))
  const field = problemField(t, p)
  if (field) parts.push(field)
  if (typeof p.line === 'number') {
    parts.push(
      typeof p.column === 'number'
        ? t('cards.common.problem.lineColumn', { line: p.line, column: p.column })
        : t('cards.common.problem.line', { n: p.line }),
    )
  }
  return parts.length ? parts.join(', ') : t('cards.common.problem.file')
}
