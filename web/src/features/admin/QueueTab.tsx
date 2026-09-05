/**
 * QueueTab — состояние очереди: сколько чего ждёт, слоты, живые воркеры.
 *
 * Считается по всей таблице заданий, а не по своим: это страница владельца, и
 * вопрос на ней — «жива ли машина», а не «что с моим отчётом».
 *
 * Перезапрашивается сама раз в несколько секунд (`QUEUE_REFETCH_MS`), поэтому
 * скелетон показывается только в первый раз: подменять таблицу заглушкой на
 * каждом обновлении значило бы мигать ею каждые пять секунд.
 */
import { useT } from '@/i18n'
import { Card, Chip, EmptyState, ErrorState, Row, SkeletonLines } from '@/ui'

import { QUEUE_REFETCH_MS, useAdminQueue } from './api'

const TH =
  'whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2'

export function QueueTab() {
  const t = useT()
  const queue = useAdminQueue()

  if (queue.isLoading) return <SkeletonLines count={6} />
  if (queue.error) return <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
  if (!queue.data) return null

  const { queued, running, by_kind, slots, workers, lost_after_s } = queue.data
  const kinds = Object.entries(by_kind)

  return (
    <div className="flex flex-col gap-s4">
      <Card
        title={t('admin.queue.title')}
        desc={t('admin.queue.live', { n: Math.round(QUEUE_REFETCH_MS / 1000) })}
      >
        <div className="flex flex-wrap gap-s6">
          <div>
            <div className="font-display text-2xl font-bold leading-none text-ink-strong">
              {queued}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">
              {t('admin.queue.queued')}
            </div>
          </div>
          <div>
            <div className="font-display text-2xl font-bold leading-none text-ink-strong">
              {running}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">
              {t('admin.queue.running')}
            </div>
          </div>
        </div>

        <div className="flex flex-col">
          <Row label={t('admin.queue.slotsMachine')}>{slots.per_machine}</Row>
          <Row label={t('admin.queue.slotsUser')}>{slots.per_user}</Row>
          <Row label={t('admin.queue.lostAfter')}>
            {t('admin.queue.seconds', { n: lost_after_s })}
          </Row>
        </div>
      </Card>

      <Card title={t('admin.queue.byKind')}>
        {kinds.length === 0 ? (
          <EmptyState
            compact
            icon="queue"
            title={t('admin.queue.empty')}
            text={t('admin.queue.emptyHint')}
          />
        ) : (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className={TH}>{t('admin.queue.kind')}</th>
                  <th className={`${TH} text-right`}>{t('admin.queue.queued')}</th>
                  <th className={`${TH} text-right`}>{t('admin.queue.running')}</th>
                </tr>
              </thead>
              <tbody>
                {kinds.map(([kind, counts]) => (
                  <tr key={kind} className="hover:bg-surface-2">
                    <td className={`${TD} font-mono text-ink`}>{kind}</td>
                    <td className={`${TD} text-right font-mono text-ink-strong`}>
                      {counts.queued}
                    </td>
                    <td className={`${TD} text-right font-mono text-ink-strong`}>
                      {counts.running}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={t('admin.queue.workers')}>
        {workers.length === 0 ? (
          <p className="text-sm text-muted">{t('admin.queue.noWorkers')}</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className={TH}>{t('admin.queue.worker')}</th>
                  <th className={TH}>{t('admin.queue.job')}</th>
                  <th className={TH}>{t('admin.queue.kind')}</th>
                  <th className={TH}>{t('admin.queue.heartbeat')}</th>
                </tr>
              </thead>
              <tbody>
                {workers.map((worker) => {
                  // Воркер, не бившийся дольше `lost_after_s`, — не «медленный»,
                  // а потерянный: по этому же числу задание поднимает соседний.
                  const age = worker.heartbeat_age_s
                  const lost = age === null || age > lost_after_s
                  return (
                    <tr key={worker.job_id} className="hover:bg-surface-2">
                      <td className={`${TD} font-mono text-ink`}>{worker.worker_id ?? '—'}</td>
                      <td className={`${TD} font-mono text-xs text-muted`}>
                        {worker.job_id.slice(0, 8)}…
                      </td>
                      <td className={`${TD} font-mono text-ink`}>{worker.kind}</td>
                      <td className={TD}>
                        <Chip tone={lost ? 'err' : 'ok'}>
                          {age === null ? '—' : t('admin.queue.seconds', { n: age })}
                        </Chip>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
