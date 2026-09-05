/**
 * StageStrip — шаги стадий сверху экрана работы.
 *
 * Семь стадий, и полоска рисуется **только там, где есть знаменатель**
 * (правило интерфейса): у «текстов» это «написано 9 из 12», у «решения» —
 * «шаг 4 из 12», а у первых трёх знаменателя нет вовсе, и там называется
 * действие. Полоска с выдуманным знаменателем врёт, поэтому её здесь нет.
 *
 * Имена стадий приходят от службы значениями по-русски (`kadai.stages`), и
 * показываются они как есть, если у сайта нет своего слова: словарь
 * `kadai.stage.*` переводит известные семь, а восьмая, появившись в службе,
 * покажется её собственным именем, а не пустотой.
 *
 * Состояние `пропущена` стоит рядом с `сделано` и отличимо от него: у работы,
 * где производить нечего, «решения» не будет, и показать его мгновенно
 * прошедшим значило бы сказать, что оно было.
 */
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, Spinner } from '@/ui'

import { DONE, RUNNING, SKIPPED, STUMBLED, type StageState } from './stages'

/** Ключ перевода имени стадии; пусто — своего слова нет, показываем как есть. */
const ПЕРЕВОД: Record<string, string> = {
  приём: 'kadai.stage.receive',
  'разбор задания': 'kadai.stage.task',
  шаблон: 'kadai.stage.structure',
  решение: 'kadai.stage.solve',
  тексты: 'kadai.stage.texts',
  сборка: 'kadai.stage.build',
  архив: 'kadai.stage.archive',
}

export function StageStrip({
  stages,
  running,
  note,
}: {
  stages: StageState[]
  running: boolean
  note: string
}) {
  const t = useT()
  if (stages.length === 0) return null

  return (
    <div className="flex flex-col gap-s2">
      <ol className="flex flex-wrap items-stretch gap-s1">
        {stages.map((стадия, i) => {
          const ключ = ПЕРЕВОД[стадия.name]
          return (
            <li key={стадия.name} className="flex items-center gap-s1">
              <div
                // Имя и состояние стадии — атрибутами, а не только цветом: по
                // ним ход работы читает сквозная проверка, а цвет темы у неё
                // свой в каждой из восьми.
                data-stage={стадия.name}
                data-state={стадия.state}
                className={cn(
                  'flex min-w-0 items-center gap-s2 rounded-btn border px-s2 py-1.5 text-xs',
                  стадия.state === DONE && 'border-ok bg-ok-bg text-ok',
                  стадия.state === RUNNING && 'border-accent bg-accent-bg text-ink-strong',
                  стадия.state === STUMBLED && 'border-err bg-err-bg text-err',
                  стадия.state === SKIPPED && 'border-line bg-surface-2 text-muted line-through',
                  стадия.state !== DONE &&
                    стадия.state !== RUNNING &&
                    стадия.state !== STUMBLED &&
                    стадия.state !== SKIPPED &&
                    'border-line bg-surface text-muted',
                )}
                title={стадия.note ?? undefined}
              >
                <Значок state={стадия.state} n={i + 1} />
                <span className="truncate font-medium">{ключ ? t(ключ) : стадия.name}</span>
                {стадия.progress && (
                  <span className="text-[11px] opacity-80">
                    {стадия.progress.done}/{стадия.progress.total}
                  </span>
                )}
              </div>
              {i < stages.length - 1 && (
                <span aria-hidden="true" className="w-3 border-t border-line" />
              )}
            </li>
          )
        })}
      </ol>
      {running && (
        <p className="flex items-center gap-s2 text-xs text-muted">
          <Spinner size={12} />
          {note || t('kadai.run.working')}
        </p>
      )}
    </div>
  )
}

function Значок({ state, n }: { state: string; n: number }) {
  if (state === DONE) return <Icon name="check" size={13} />
  if (state === RUNNING) return <Spinner size={12} />
  if (state === STUMBLED) return <Icon name="error" size={13} />
  if (state === SKIPPED) return <Icon name="close" size={13} />
  return <span className="font-mono text-[11px] opacity-70">{n}</span>
}
