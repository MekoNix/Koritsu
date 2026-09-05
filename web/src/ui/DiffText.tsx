/**
 * DiffText — сравнение двух текстов по словам, одним потоком.
 *
 * Общий компонент: им пользуются история значений тега (`features/reports`) и
 * история списка блоков (`features/kadai`). Ничего своего он не грузит и ни о
 * какой области не знает — на входе две строки, на выходе размеченный текст.
 *
 * **Одним потоком, а не двумя колонками.** Две колонки «было | стало» удобны
 * для кода, где строки выровнены; у нас сравниваются абзацы, и правка в них
 * почти всегда — переставленное слово внутри строки. В колонках такая правка
 * читается как «весь абзац изменился», а здесь видно ровно то слово, которое
 * тронули.
 *
 * Цвета — переменные темы (`--ok`, `--err`), поэтому сравнение выглядит
 * одинаково правильно во всех четырёх темах и в тёмном режиме. Одного цвета
 * мало: дальтонизм и печать — поэтому у удалённого ещё и зачёркивание, а у
 * добавленного подчёркивание. Слово «зелёное» нигде не сказано и в подписи —
 * подпись называет действие («добавлено», «убрано»), а не краску.
 */
import { useMemo } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { diffStats, diffWords } from '@/lib/diffWords'

export type DiffTextProps = {
  /** Что было (старая версия). */
  before: string
  /** Что стало (новая версия). */
  after: string
  /** Показывать ли строку «добавлено N, убрано M». */
  showStats?: boolean
  className?: string
}

export function DiffText({ before, after, showStats = true, className }: DiffTextProps) {
  const t = useT()
  // Пересчитывается только при смене текстов: сравнение — это матрица, и
  // считать её на каждую перерисовку окна было бы расточительно.
  const куски = useMemo(() => diffWords(before, after), [before, after])
  const счёт = useMemo(() => diffStats(куски), [куски])
  const одинаковы = счёт.added === 0 && счёт.removed === 0

  return (
    <div className={cn('flex flex-col gap-s2', className)}>
      {showStats && (
        <p className="text-xs text-muted">
          {одинаковы ? (
            t('common.diff.same')
          ) : (
            <>
              <span className="text-ok">{t('common.diff.added', { n: счёт.added })}</span>
              {' · '}
              <span className="text-err">{t('common.diff.removed', { n: счёт.removed })}</span>
            </>
          )}
        </p>
      )}
      <p className="whitespace-pre-wrap break-words font-body text-sm text-ink">
        {куски.map((кусок, i) =>
          кусок.kind === 'same' ? (
            <span key={i}>{кусок.text}</span>
          ) : кусок.kind === 'add' ? (
            <ins
              key={i}
              className="rounded-sm bg-ok-bg text-ok decoration-1 underline-offset-2"
              // `ins`/`del` — не украшение: скринридер объявляет их как
              // вставку и удаление, и человек без экрана узнаёт то же, что
              // человек с цветом.
            >
              {кусок.text}
            </ins>
          ) : (
            <del key={i} className="rounded-sm bg-err-bg text-err decoration-1">
              {кусок.text}
            </del>
          ),
        )}
      </p>
    </div>
  )
}
