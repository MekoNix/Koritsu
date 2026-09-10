/**
 * StageStrip — шаги стадий сверху экрана работы и ход внутри текущей стадии.
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
 *
 * **«Ждёт вас» — восьмое состояние, и в снимке стадий его нет.** Стадия, на
 * которой сценарий остановился показать сделанное, по своим меркам всё ещё
 * идёт: работы у неё не убавилось, просто дальше её двигает человек. Пока это
 * не названо, полоска показывает бесконечно идущую стадию — то есть выглядит
 * как зависшая. Поэтому имя ждущей стадии приезжает пропсом (`hold`, из поля
 * `hold` снимка) и рисуется поверх её собственного состояния.
 *
 *     Почему ход показывается двумя способами
 *     ---------------------------------------
 *
 * Строка «сейчас: …» отвечает на вопрос «работает ли оно вообще», и ответ ей
 * нужен один — последний. Журнал отвечает на другой вопрос, «что оно
 * наработало», и там нужен список. Одно вместо другого не годится: строка,
 * растущая в ленту, съедает экран, а свёрнутый журнал во время прогона молчит.
 */
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, Progress, Spinner } from '@/ui'

import { DONE, RUNNING, SKIPPED, STUMBLED, type Move, type StageState } from './stages'

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
  moves = [],
  hold = null,
}: {
  stages: StageState[]
  running: boolean
  note: string
  /** Ходы внутри стадий: последний идёт строкой, все — в журнал. */
  moves?: Move[]
  /** Имя стадии, которая ждёт человека, или `null`. */
  hold?: string | null
}) {
  const t = useT()
  if (stages.length === 0) return null

  const шаг = moves.length > 0 ? moves[moves.length - 1] : null
  // Доля считается только по знаменателю от службы: у петли решения потолок
  // ходов известен, у прочих стадий — нет, и там полоски не будет вовсе.
  const доля = шаг && шаг.total > 0 ? шаг.n / шаг.total : 0

  return (
    <div className="flex flex-col gap-s2">
      <ol className="flex flex-wrap items-stretch gap-s1">
        {stages.map((стадия, i) => {
          const ключ = ПЕРЕВОД[стадия.name]
          const ждёт_вас = стадия.name === hold
          return (
            <li key={стадия.name} className="flex items-center gap-s1">
              <div
                // Имя и состояние стадии — атрибутами, а не только цветом: по
                // ним ход работы читает сквозная проверка, а цвет темы у неё
                // свой в каждой из восьми.
                data-stage={стадия.name}
                data-state={стадия.state}
                data-hold={ждёт_вас || undefined}
                className={cn(
                  'flex min-w-0 items-center gap-s2 rounded-btn border px-s2 py-1.5 text-xs',
                  ждёт_вас && 'border-warn bg-warn-bg text-warn',
                  !ждёт_вас && стадия.state === DONE && 'border-ok bg-ok-bg text-ok',
                  !ждёт_вас &&
                    стадия.state === RUNNING &&
                    'border-accent bg-accent-bg text-ink-strong',
                  !ждёт_вас && стадия.state === STUMBLED && 'border-err bg-err-bg text-err',
                  !ждёт_вас &&
                    стадия.state === SKIPPED &&
                    'border-line bg-surface-2 text-muted line-through',
                  !ждёт_вас &&
                    стадия.state !== DONE &&
                    стадия.state !== RUNNING &&
                    стадия.state !== STUMBLED &&
                    стадия.state !== SKIPPED &&
                    'border-line bg-surface text-muted',
                )}
                title={стадия.note ?? undefined}
              >
                <Значок state={стадия.state} n={i + 1} hold={ждёт_вас} />
                <span className="truncate font-medium">{ключ ? t(ключ) : стадия.name}</span>
                {ждёт_вас && (
                  <span className="whitespace-nowrap text-[11px] font-semibold">
                    {t('kadai.stage.waitsYou')}
                  </span>
                )}
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
        <>
          <p className="flex flex-wrap items-center gap-s2 text-xs text-muted">
            <Spinner size={12} />
            <span className="text-ink">{note || t('kadai.run.working')}</span>
            {шаг && шаг.total > 0 && (
              <span className="font-mono">
                {t('kadai.run.moveOf', { n: шаг.n, total: шаг.total })}
              </span>
            )}
          </p>
          {доля > 0 && <Progress value={доля} label={t('kadai.run.moves')} />}
        </>
      )}

      {/* Журнал ходов — `<details>`, а не своё состояние: браузер уже умеет и
          клавиатуру, и доступность этого. Свёрнут по умолчанию: во время
          прогона на экране нужна одна строка «сейчас», а весь список читают
          потом, когда спрашивают «что он там наработал». */}
      {moves.length > 0 && (
        <details className="rounded-md border border-line bg-surface-2 text-xs">
          <summary className="cursor-pointer px-s3 py-s2 text-muted focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent">
            {t('kadai.run.log', { n: moves.length })}
          </summary>
          <ol className="flex flex-col gap-1 px-s3 pb-s3">
            {moves.map((ход) => (
              <li key={ход.seq} className="flex items-start gap-s2">
                <Icon
                  name={ход.ok ? 'check' : 'error'}
                  size={13}
                  className={cn('mt-0.5 shrink-0', ход.ok ? 'text-ok' : 'text-err')}
                />
                <span className="min-w-0 flex-1 text-ink">{ход.note}</span>
                {ход.stage && <span className="shrink-0 text-muted">{ход.stage}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}

function Значок({ state, n, hold }: { state: string; n: number; hold: boolean }) {
  // У ждущей стадии не крутится спиннер: он говорит «идёт работа», а работа
  // как раз стоит и ждёт слова человека.
  if (hold) return <Icon name="info" size={13} />
  if (state === DONE) return <Icon name="check" size={13} />
  if (state === RUNNING) return <Spinner size={12} />
  if (state === STUMBLED) return <Icon name="error" size={13} />
  if (state === SKIPPED) return <Icon name="close" size={13} />
  return <span className="font-mono text-[11px] opacity-70">{n}</span>
}
