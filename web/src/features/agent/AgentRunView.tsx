/**
 * AgentRunView — ход работы, ответ модели и итог прогона.
 *
 * Три вещи в одном столбце, в том порядке, в каком они появляются: прогресс —
 * ходы — текст — что изменилось. Разворачивать их вкладками, как в макете
 * («Ход работы / Результаты / Лог»), незачем: у нас нет ни лога наружу
 * (инструменты и аргументы не уезжают), ни артефактов
 * отдельным списком — итог прогона это ключи тегов, и он короткий.
 *
 * Ход — это поставленный тег. Другого события служба не шлёт, и придумывать
 * шаги, которых нет в потоке, значило бы рисовать выдуманный план.
 */
import { Link } from 'react-router-dom'

import { errorText } from '@/api'
import { t as translate, useT } from '@/i18n'
import { Chip, Icon, Progress, Spinner } from '@/ui'

import { tagHref } from './context'
import type { AgentRunState } from './useAgentRun'

/** Пилюля состояния задания. */
function StatusChip({ status }: { status: string }) {
  const t = useT()
  const TONES = {
    queued: 'muted',
    running: 'accent',
    done: 'ok',
    failed: 'err',
    cancelled: 'warn',
  } as const
  const tone = (TONES as Record<string, 'muted' | 'accent' | 'ok' | 'err' | 'warn'>)[status]
  return <Chip tone={tone ?? 'muted'}>{t(`agent.status.${status}`)}</Chip>
}

/**
 * Почему прогон упал — строкой для человека.
 *
 * Тем же путём, что у тоста оболочки (`useUserEvents.failedReason`): код из
 * задания, русский текст ему даёт общий словарь отказов. Незнакомый код второй
 * строки не даёт вовсе — английское `handler_failed` в панели хуже, чем его
 * отсутствие.
 */
function failedReason(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | null)?.code
  if (typeof code !== 'string' || !code) return undefined
  const текст = translate(`errors.${code}`)
  return текст === `errors.${code}` ? undefined : текст
}

/** Чем именно кончился прогон, если для этого исхода есть русское слово. */
function outcomeText(outcome: string | undefined): string | undefined {
  if (!outcome) return undefined
  const текст = translate(`agent.outcome.${outcome}`)
  return текст === `agent.outcome.${outcome}` ? undefined : текст
}

/**
 * Дошёл ли прогон до конца.
 *
 * Два признака, а не один, потому что признак зависит от того, кто уронил
 * задание. Служба роняет прогон, кончившийся не «готово», кодом `run_failed`,
 * и итога прогона при этом в карточке задания нет вовсе: отказ обработчика не
 * несёт `result`. Остальные коды (`no_key`, `limit_exhausted`) — это беды до
 * прогона, и говорить про них «дошёл не до конца» неправда: прогон не
 * начинался.
 */
function недошёл(run: AgentRunState): boolean {
  const code = (run.job?.error as { code?: unknown } | null | undefined)?.code
  return code === 'run_failed' || run.result?.ok === false
}

export function AgentRunView({ run, projectId }: { run: AgentRunState; projectId: string }) {
  const t = useT()
  const status = run.job?.status ?? ''
  const доля = run.total > 0 ? run.step / run.total : 0

  // Отказ постановки показывается и тогда, когда задания нет вовсе: «остатка не
  // хватило» приходит вместо задания, и молчащая панель в этом случае выглядит
  // как заевшая кнопка.
  if (!run.job && !run.starting && !run.startError) return null

  return (
    <div className="flex flex-col gap-s3">
      {/* Прогресс. Полоса рисуется только когда служба назвала число шагов:
          доля от неизвестного целого — это врущая полоса. */}
      <div className="flex items-center gap-s2 text-xs text-muted">
        {run.running && <Spinner size={14} />}
        {status && <StatusChip status={status} />}
        {run.total > 0 && (
          <span className="font-mono">
            {t('agent.progress.step', { step: run.step, total: run.total })}
          </span>
        )}
      </div>
      {run.total > 0 && <Progress value={доля} label={t('agent.progress.label')} />}

      {/* Ходы. */}
      {run.moves.length > 0 && (
        <ul className="flex flex-col gap-1">
          {run.moves.map((ход) => (
            <li key={ход.seq} className="flex items-center gap-s2 text-sm text-ink">
              <Icon name="check" size={14} className="shrink-0 text-ok" />
              <Link
                to={tagHref(projectId, ход.key)}
                className="truncate font-mono text-xs underline"
              >
                {ход.key}
              </Link>
              <span className="truncate text-xs text-muted">{t('agent.moves.tagFilled')}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Ответ модели. Приходит одним куском в конце прогона: у петли
          инструментов потока наружу нет (`runs/handlers/agent.py`). */}
      {run.text && (
        <div className="rounded-sm border border-dashed border-agent bg-agent-bg p-s3 text-sm leading-normal text-ink">
          <div className="mb-1 text-xs font-semibold text-agent">{t('agent.text.title')}</div>
          <p className="whitespace-pre-wrap break-words">{run.text}</p>
        </div>
      )}

      {run.limitExhausted && <p className="text-xs text-err">{t('agent.limit')}</p>}

      {/* Задание упало: тоста здесь нет (его даёт оболочка), но строка нужна —
          человек смотрит в панель, а не в угол экрана.

          Сюда приходит и прогон, кончившийся не «готово»: служба роняет
          такое задание кодом `run_failed`, и ветка провала одна — та же, что
          у оболочки. Строка «дошёл не до конца» стоит рядом: код отвечает на
          вопрос «что случилось», а `outcome` — «на чём именно», и «модель не
          ответила» человек чинит не так, как «кончились ходы». */}
      {status === 'failed' && (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs text-err">
            {t('agent.result.failed')}
            {failedReason(run.job?.error) ? ` · ${failedReason(run.job?.error)}` : ''}
          </p>
          {недошёл(run) && (
            <p className="text-xs text-warn">
              {t('agent.result.notOk')}
              {outcomeText(run.result?.outcome) ? ` · ${outcomeText(run.result?.outcome)}` : ''}
            </p>
          )}
        </div>
      )}

      {/* Итог: что изменилось. */}
      {!run.running && run.job && status === 'done' && (
        <div className="flex flex-col gap-s2 rounded-sm border border-line bg-surface-2 p-s3">
          <div className="text-xs font-semibold text-ink-strong">{t('agent.result.title')}</div>
          {/* Задание кончилось штатно, а прогон — нет: у уровня 3 обрыв модели
              и потолок ходов дают `done` с `ok: false` (обработчик службы), и
              оболочка про такой случай не тостит. Молчать здесь нельзя: без
              строки «дошёл не до конца» пустой список читается как «агенту
              нечего было менять». */}
          {run.result?.ok === false && (
            <p className="text-xs text-warn">
              {t('agent.result.notOk')}
              {outcomeText(run.result.outcome) ? ` · ${outcomeText(run.result.outcome)}` : ''}
            </p>
          )}
          {run.changed.length === 0 ? (
            <p className="text-xs text-muted">{t('agent.result.none')}</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {run.changed.map((ключ) => (
                <li key={ключ}>
                  <Link
                    to={tagHref(projectId, ключ)}
                    className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-0.5 font-mono text-xs text-ink hover:border-agent"
                  >
                    <Icon name="file" size={12} aria-hidden="true" />
                    {ключ}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="font-mono text-xs text-muted">
            {t('agent.result.counts', {
              steps: run.result?.steps ?? 0,
              calls: run.result?.calls ?? 0,
            })}
          </p>
        </div>
      )}

      {/* Отказ постановки: лимит, нет ключа, слишком длинная задача. */}
      {!!run.startError && <p className="text-xs text-err">{errorText(run.startError)}</p>}
    </div>
  )
}
