/**
 * versions — чистая часть истории версий: типы, разбор ответа службы, выбор пар.
 *
 * Отдельным файлом от `VersionHistory.tsx` и `TagVersions.tsx` не по вкусу, а по
 * правилу: файл, экспортирующий и компонент, и функции, теряет горячую
 * перезагрузку (`react-refresh/only-export-components`). Заодно это то, что
 * проверяется тестом (`versions.test.ts`) без единого рендера.
 */
import type { t as translate } from '@/i18n'

import type { VersionHead } from './types'

/** Одна строка истории. Ровно то, что рисуется, — без полей «на всякий случай». */
export type VersionEntry = {
  n: number
  /** Время в ISO — форматируется здесь, одинаково у тегов и у блоков. */
  at: string
  /** `agent` | `manual` | `file` | `template` — подпись даёт `sourceLabel`. */
  source: string
  /** Правая подпись строки: «возврат версии 3», «блоков 12», заметка правки. */
  note?: string | null
}

/** Ответ хука «дай текст версии»: то же, что у запроса, но без TanStack. */
export type VersionText = {
  text: string | undefined
  loading: boolean
  error: unknown
}

/** Время версии человеку: дата и часы, без секунд и без «менее минуты назад». */
export function когда(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Какие две версии сравнивать. → `[левая, правая]`, младшая слева.
 *
 * Чистая функция и отдельно от экрана, потому что правило здесь не очевидное и
 * проверяется тестом: одна отметка означает «эта и текущая», две — «эти две»,
 * отметка самой текущей означает «текущая и та, что была до неё» (сравнивать
 * её с собой было бы пустым экраном), а нуль отметок — что сравнивать нечего.
 *
 * `versions` — номера версий в порядке службы (старые сверху), последний из
 * них и есть текущая.
 */
export function сравниваемые(picked: number[], versions: number[]): [number | null, number | null] {
  const текущая = versions[versions.length - 1] ?? null
  const первая = picked[0]
  if (первая === undefined) return [null, null]
  const вторая = picked[1]
  if (вторая === undefined) {
    if (первая === текущая) return [versions[versions.length - 2] ?? null, первая]
    return [первая, текущая]
  }
  return [Math.min(первая, вторая), Math.max(первая, вторая)]
}

/**
 * Версии службы → строки общей истории.
 *
 * Отдельной чистой функцией, потому что здесь единственное место, где сайт
 * толкует ответ службы: **возврат виден только по флагу.** `source` у
 * возвращённой версии сохраняется от той, которую вернули
 * (`orchestrator.Project.rollback`) — значение по-прежнему написано моделью
 * или рукой, а не «возвратом». Что это был возврат, служба пишет флагом
 * `вернули версию N`. Строка флага русская и приходит от службы; разбираем её
 * числом, а показываем свой текст — иначе в интерфейсе появилась бы фраза,
 * которой нет ни в одном словаре.
 */
export function versionEntries(
  versions: VersionHead[] | undefined,
  t: typeof translate,
): VersionEntry[] {
  return (versions ?? []).map((v) => ({
    n: v.n,
    at: v.at,
    source: v.source,
    note: заметка(v, t),
  }))
}

/**
 * Заметка строки: возврат виден только по флагу. (см. `versionEntries`)
 */
export function заметка(v: VersionHead, t: typeof translate): string | null {
  for (const флаг of v.flags ?? []) {
    const найдено = /вернули версию (\d+)/.exec(флаг)
    if (найдено?.[1]) return t('reports.versions.restoredFrom', { n: найдено[1] })
  }
  return null
}
