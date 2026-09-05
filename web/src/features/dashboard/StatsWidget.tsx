/**
 * StatsWidget — широкая плитка со счётчиками: работ, заданий в очереди, места
 * на томе.
 *
 * Считается по тем же ответам, что уже лежат в кэше (список проектов и очередь
 * заданий), поэтому отдельного «маршрута статистики» службе не нужно, а цифры
 * не расходятся с тем, что человек видит на соседних экранах.
 *
 * Дедлайнов, семестров и учебных групп здесь нет и не будет: приложением
 * пользуется не только студент, и таких данных у службы нет.
 */
import { useT } from '@/i18n'
import { Skeleton } from '@/ui'
import { useCurrentWorkspace } from '@/api/hooks'
import { useProjects } from '@/features/projects/data'
import { formatBytes, plural } from '@/features/projects/format'

import { Widget } from './Widget'
import { useQueueSize } from './data'

export function StatsWidget() {
  const t = useT()
  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id)
  const queue = useQueueSize()

  const список = projects.data ?? []
  const занято = список.reduce((sum, project) => sum + project.bytes_used, 0)

  const цифры = [
    {
      key: 'works',
      value: projects.isPending ? null : String(список.length),
      label: plural(список.length, [
        t('dashboard.stats.works.one'),
        t('dashboard.stats.works.few'),
        t('dashboard.stats.works.many'),
      ]),
    },
    {
      key: 'queue',
      value: queue.isPending ? null : String(queue.data ?? 0),
      label: plural(queue.data ?? 0, [
        t('dashboard.stats.queue.one'),
        t('dashboard.stats.queue.few'),
        t('dashboard.stats.queue.many'),
      ]),
    },
    {
      key: 'bytes',
      value: projects.isPending ? null : formatBytes(t, занято),
      label: t('dashboard.stats.storage'),
    },
  ]

  return (
    <Widget title={t('dashboard.stats.title')}>
      <dl className="grid grid-cols-3 gap-s4">
        {цифры.map((цифра) => (
          <div key={цифра.key} className="min-w-0">
            <dt className="sr-only">{цифра.label}</dt>
            <dd className="flex flex-col gap-1">
              {цифра.value === null ? (
                <Skeleton className="h-7 w-16" />
              ) : (
                <span className="font-display text-2xl font-bold tracking-tight text-ink-strong">
                  {цифра.value}
                </span>
              )}
              <span className="truncate text-xs uppercase tracking-wider text-muted">
                {цифра.label}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </Widget>
  )
}
