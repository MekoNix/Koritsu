/**
 * AgentHistory — последние прогоны агента в этой работе.
 *
 * Зачем она в панели: «не нравится — перегенерируй» из брифа работает только
 * тогда, когда видно, что уже просили. История приезжает из очереди
 * (`GET /api/jobs?project_id=…`), а не копится в браузере: прогон переживает
 * закрытую вкладку, и список, собранный в памяти, после перезагрузки соврал бы.
 *
 * Задача каждого прогона показана его же словами — она лежит в `payload.task`
 * карточки задания. Нажатие «повторить» кладёт её обратно в поле, а не
 * запускает сразу: то же слово в другой день значит другое, и человек имеет
 * право поправить его перед деньгами.
 */
import { useT } from '@/i18n'
import { Button, Chip, SkeletonLines } from '@/ui'
import type { Job } from '@/api/hooks'

import { useAgentRuns } from './data'

const TONES = {
  queued: 'muted',
  running: 'accent',
  done: 'ok',
  failed: 'err',
  cancelled: 'warn',
} as const

function taskOf(job: Job): string {
  const payload = (job.payload ?? {}) as { task?: unknown }
  return typeof payload.task === 'string' ? payload.task : ''
}

export function AgentHistory({
  projectId,
  onRepeat,
}: {
  projectId: string
  onRepeat: (task: string) => void
}) {
  const t = useT()
  const runs = useAgentRuns(projectId)

  if (runs.isPending) return <SkeletonLines count={2} />
  const список = runs.data ?? []
  if (!список.length) return null

  return (
    <section className="flex flex-col gap-s2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
        {t('agent.history.title')}
      </h3>
      <ul className="flex flex-col gap-1.5">
        {список.map((job) => {
          const задача = taskOf(job)
          const tone = (TONES as Record<string, 'muted' | 'accent' | 'ok' | 'err' | 'warn'>)[
            job.status
          ]
          return (
            <li
              key={job.id}
              className="flex items-start gap-s2 rounded-sm border border-line bg-surface p-s2"
            >
              <Chip tone={tone ?? 'muted'}>{t(`agent.status.${job.status}`)}</Chip>
              <p className="min-w-0 flex-1 truncate text-xs text-ink" title={задача}>
                {задача || t('agent.history.noTask')}
              </p>
              {!!задача && (
                <Button variant="ghost" size="sm" onClick={() => onRepeat(задача)}>
                  {t('agent.history.repeat')}
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
