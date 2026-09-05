/**
 * VersionHistory — история версий со сравнением текстов и возвратом.
 *
 * Общий компонент двух областей: значения тега (`features/reports`) и списка
 * блоков (`features/kadai`). Он ничего не грузит сам — на входе готовый список
 * версий, хук «дай текст версии N» и обработчик возврата. Отсюда и три пропса
 * из задания: **список версий, загрузить версию, вернуть**.
 *
 *     Почему хук пропсом, а не адрес маршрута
 *     ---------------------------------------
 *
 * Маршруты у тега и у блоков разные (`…/values/{key}/versions/{n}` против
 * `…/blocks/versions/{n}`), и форма ответа разная. Знать про оба здесь значило
 * бы завести в общем компоненте ветвление по области. Поэтому вызывающий даёт
 * готовый хук: он зовётся ровно дважды, на верхнем уровне, для левой и правой
 * стороны сравнения, — правило хуков соблюдено, потому что количество вызовов
 * от выбора человека не зависит.
 *
 *     «Эта и текущая» против «две выбранные»
 *     --------------------------------------
 *
 * Отметили одну версию — она сравнивается с текущей: это тот вопрос, который
 * задают в девяти случаях из десяти («что изменилось с тех пор»). Отметили
 * вторую — сравниваются они между собой. Третья отметка вытесняет старшую из
 * двух, а не отказывает молча: человек, ткнувший в третью строку, хочет
 * увидеть её, а не сообщение о том, что больше двух нельзя.
 *
 * Возврат спрашивает подтверждение — и в вопросе сказано главное: **возврат
 * ничего не удаляет**. Служба дописывает выбранное значение новой версией
 * (`versions/routes.py`), поэтому номер в ответе больше того, к которому
 * вернулись, и терять человеку нечего.
 */
import { useMemo, useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Dialog, DiffText, Icon, SkeletonLines } from '@/ui'

import { когда, сравниваемые, type VersionEntry, type VersionText } from './versions'

export type { VersionEntry, VersionText } from './versions'

export type VersionHistoryProps = {
  /** Версии, старые сверху (в том порядке, в каком отдаёт служба). */
  entries: VersionEntry[] | undefined
  loading?: boolean
  error?: unknown
  /**
   * Хук «дай текст версии N». `null` — сравнивать нечего, хук обязан не
   * ходить в службу и вернуть `text: undefined`.
   */
  useVersionText: (n: number | null) => VersionText
  /** Текущий текст: правая сторона сравнения, когда отмечена одна версия. */
  currentText: string
  /** Вернуть версию. Подтверждение уже спрошено. */
  onRollback: (n: number) => void
  canEdit: boolean
  rollbackPending?: boolean
  rollbackError?: unknown
  /** Как назвать источник версии человеку. По умолчанию — сам источник. */
  sourceLabel?: (source: string) => string
  /** Что написать, когда версий нет вовсе. */
  emptyText?: string
}

export function VersionHistory({
  entries,
  loading,
  error,
  useVersionText,
  currentText,
  onRollback,
  canEdit,
  rollbackPending,
  rollbackError,
  sourceLabel,
  emptyText,
}: VersionHistoryProps) {
  const t = useT()
  // Отмеченные версии, в порядке отметки: первая — левая сторона сравнения.
  const [picked, setPicked] = useState<number[]>([])
  const [asking, setAsking] = useState<number | null>(null)

  // `useMemo` не ради скорости, а ради стабильной ссылки: без неё `entries ?? []`
  // давал бы новый массив на каждую перерисовку, и сравнение пересчитывалось бы
  // впустую вместе с ним.
  const список = useMemo(() => entries ?? [], [entries])
  const текущая = список[список.length - 1]?.n ?? null

  // Левая сторона — младший номер, правая — старший: сравнение читается
  // «было → стало», а не «как получилось отметить».
  const [левая, правая] = useMemo(
    () =>
      сравниваемые(
        picked,
        список.map((v) => v.n),
      ),
    [picked, список],
  )

  // Текущая версия читается из `currentText`, а не запросом: её текст уже на
  // экране, и второй запрос за тем же показал бы скелетон вместо готового.
  const левый_текст = useVersionText(левая !== null && левая !== текущая ? левая : null)
  const правый_текст = useVersionText(правая !== null && правая !== текущая ? правая : null)

  const before = левая === null ? '' : левая === текущая ? currentText : левый_текст.text
  const after = правая === null ? '' : правая === текущая ? currentText : правый_текст.text
  const сравнение_грузится =
    (левая !== null && левая !== текущая && левый_текст.loading) ||
    (правая !== null && правая !== текущая && правый_текст.loading)
  const сравнение_беда =
    (левая !== null && левая !== текущая && левый_текст.error) ||
    (правая !== null && правая !== текущая && правый_текст.error) ||
    null

  function отметить(n: number) {
    setPicked((было) => {
      if (было.includes(n)) return было.filter((x) => x !== n)
      const [первая, вторая] = было
      if (первая === undefined || вторая === undefined) return [...было, n]
      // Третья отметка вытесняет старшую из двух (см. докстроку модуля).
      return [Math.min(первая, вторая), n]
    })
  }

  if (loading) return <SkeletonLines count={3} />
  if (error || список.length === 0) {
    // 404 у тега без единого значения — это «истории нет», а не беда: служба
    // отвечает так на всякий тег, которого ещё не касались.
    return <p className="text-xs text-muted">{emptyText ?? t('reports.versions.none')}</p>
  }

  return (
    <div className="flex flex-col gap-s3">
      <ul className="flex flex-col gap-s1">
        {[...список].reverse().map((v) => {
          const отмечена = picked.includes(v.n)
          return (
            <li
              key={v.n}
              className={cn(
                'flex items-center gap-s2 rounded-sm px-s2 py-1.5 text-xs',
                отмечена ? 'bg-accent-bg' : 'hover:bg-surface-2',
              )}
            >
              <label className="flex shrink-0 cursor-pointer items-center gap-s2">
                <input
                  type="checkbox"
                  checked={отмечена}
                  onChange={() => отметить(v.n)}
                  className="accent-[var(--accent)]"
                  aria-label={t('reports.versions.compareWith', { n: v.n })}
                />
                <span className="font-mono text-ink-strong">v{v.n}</span>
              </label>
              {/* Приметы версии переносятся внутри себя, а кнопка стоит на месте:
                  колонка узкая, и «Вернуть», уехавшее на вторую строку у одной
                  строки из трёх, делает список рваным. */}
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-s2">
                <span className={v.source === 'agent' ? 'text-agent' : 'text-muted'}>
                  {sourceLabel ? sourceLabel(v.source) : v.source}
                </span>
                <span className="text-muted">{когда(v.at)}</span>
                {v.note && <span className="text-muted">· {v.note}</span>}
                {v.n === текущая && (
                  <span className="rounded-sm bg-ok-bg px-1.5 py-0.5 text-ok">
                    {t('reports.versions.current')}
                  </span>
                )}
              </span>
              <Button
                className="shrink-0"
                variant="secondary"
                size="sm"
                disabled={!canEdit || rollbackPending || v.n === текущая}
                onClick={() => setAsking(v.n)}
              >
                {t('reports.versions.rollback')}
              </Button>
            </li>
          )
        })}
      </ul>

      {rollbackError != null && <p className="text-xs text-err">{errorText(rollbackError)}</p>}

      <section className="rounded-md border border-line bg-surface-2 p-s3">
        <h4 className="mb-s2 flex items-center gap-s2 text-xs font-semibold text-ink-strong">
          <Icon name="copy" size={13} />
          {левая === null
            ? t('reports.versions.compareTitle')
            : t('reports.versions.compareOf', { a: левая ?? 0, b: правая ?? 0 })}
        </h4>
        {левая === null ? (
          <p className="text-xs text-muted">{t('reports.versions.compareHint')}</p>
        ) : сравнение_грузится ? (
          <SkeletonLines count={4} />
        ) : сравнение_беда ? (
          <p className="text-xs text-err">{errorText(сравнение_беда)}</p>
        ) : (
          <DiffText before={before ?? ''} after={after ?? ''} />
        )}
      </section>

      <Dialog
        open={asking !== null}
        onOpenChange={(v) => !v && setAsking(null)}
        title={t('reports.versions.rollbackTitle', { n: asking ?? 0 })}
        description={t('reports.versions.rollbackHint')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAsking(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="primary"
              loading={rollbackPending}
              onClick={() => {
                if (asking !== null) onRollback(asking)
                setAsking(null)
              }}
            >
              {t('reports.versions.rollback')}
            </Button>
          </>
        }
      />
    </div>
  )
}
