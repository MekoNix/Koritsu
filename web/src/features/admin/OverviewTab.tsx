/**
 * OverviewTab — первая вкладка админки: плитки и три графика за период.
 *
 * Отвечает на вопрос, на который не отвечали ни список людей, ни очередь:
 * «что происходит со временем». Список знает расход одним числом за
 * календарный месяц, очередь — что в ней прямо сейчас; ни тот, ни другая не
 * скажут, растёт ли расход и когда приходят люди.
 *
 * Данные — из двух запросов, и это не оплошность: ряды (`/api/admin/stats`)
 * меняются раз в сутки, а очередь перезапрашивается каждые пять секунд
 * (`QUEUE_REFETCH_MS`). Слить их в один запрос значило бы либо тянуть годовой
 * ряд каждые пять секунд, либо показывать очередь позавчерашней.
 *
 * Пустая база — это «данных пока нет», а не беда: свежая служба обязана
 * открываться без единого красного пятна.
 */
import { useMemo, useState } from 'react'

import { useT } from '@/i18n'
import { Card, EmptyState, ErrorState, Segmented, Skeleton, SkeletonLines } from '@/ui'
import { formatUnits } from '@/features/settings/format'

import { PERIODS, useAdminQueue, useAdminStats, type Period } from './api'
import { ColumnChart, KindBars, StatTile } from './Chart'
import { fillDays, sumOf } from './chart'

export function OverviewTab() {
  const t = useT()
  const [дней, задатьПериод] = useState<Period>(30)
  const stats = useAdminStats(дней)
  const queue = useAdminQueue()

  // Ряды приводятся к плотному виду и здесь тоже. Служба уже отдаёт их
  // плотными, но график, который молча врёт при разреженном ряде, — это график,
  // который однажды соврёт: см. `chart.fillDays`.
  const расход = useMemo(
    () =>
      stats.data
        ? fillDays(
            stats.data.since,
            stats.data.days,
            stats.data.usage_by_day.map((т) => ({ day: т.day, value: т.units })),
          )
        : [],
    [stats.data],
  )
  const регистрации = useMemo(
    () =>
      stats.data
        ? fillDays(
            stats.data.since,
            stats.data.days,
            stats.data.registrations_by_day.map((т) => ({ day: т.day, value: т.count })),
          )
        : [],
    [stats.data],
  )

  /** Короткое число для оси: длинное там не помещается уже на сотне тысяч. */
  const краткое = (value: number): string => {
    if (value >= 1_000_000)
      return t('admin.overview.short.mln', {
        n: (value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1).replace('.', ','),
      })
    if (value >= 1000)
      return t('admin.overview.short.k', {
        n: (value / 1000).toFixed(value >= 10_000 ? 0 : 1).replace('.', ','),
      })
    return formatUnits(Math.round(value))
  }

  const период = (
    <Segmented
      value={String(дней)}
      label={t('admin.overview.period')}
      size="sm"
      options={PERIODS.map((n) => ({ value: String(n), label: t('admin.overview.days', { n }) }))}
      onChange={(значение) => задатьПериод(Number(значение) as Period)}
    />
  )

  if (stats.isLoading) {
    return (
      <div className="flex flex-col gap-s4">
        <div className="grid grid-cols-2 gap-s3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[72px]" />
          ))}
        </div>
        <SkeletonLines count={6} />
      </div>
    )
  }
  if (stats.error) return <ErrorState error={stats.error} onRetry={() => void stats.refetch()} />
  if (!stats.data) return null

  const всегоЗаПериод = sumOf(расход)
  const пусто =
    всегоЗаПериод === 0 && stats.data.jobs_by_kind.length === 0 && sumOf(регистрации) === 0

  return (
    <div className="flex flex-col gap-s4">
      <div className="flex flex-wrap items-center justify-between gap-s3">
        <span className="text-xs text-muted">{t('admin.overview.hint')}</span>
        {период}
      </div>

      <div className="grid grid-cols-2 gap-s3 lg:grid-cols-4">
        <StatTile
          value={formatUnits(всегоЗаПериод)}
          label={t('admin.overview.tile.spent')}
          hint={t('admin.overview.days', { n: дней })}
        />
        <StatTile
          value={formatUnits(stats.data.active_users)}
          label={t('admin.overview.tile.active')}
          hint={t('admin.overview.tile.activeHint')}
        />
        <StatTile
          value={queue.data ? formatUnits(queue.data.queued) : '—'}
          label={t('admin.overview.tile.queued')}
          hint={
            queue.data
              ? t('admin.overview.tile.runningHint', { n: queue.data.running })
              : t('admin.overview.tile.noQueue')
          }
        />
        <StatTile
          value={queue.data ? formatUnits(queue.data.slots.per_machine) : '—'}
          label={t('admin.overview.tile.slots')}
          hint={
            queue.data
              ? t('admin.overview.tile.slotsHint', { n: queue.data.slots.per_user })
              : t('admin.overview.tile.noQueue')
          }
        />
      </div>

      {пусто ? (
        <Card title={t('admin.overview.title')}>
          <EmptyState
            icon="chart"
            title={t('admin.overview.empty')}
            text={t('admin.overview.emptyHint')}
          />
        </Card>
      ) : (
        <>
          <Card title={t('admin.overview.usage')} desc={t('admin.overview.usageHint')}>
            <ColumnChart
              points={расход}
              label={t('admin.overview.usage')}
              valueLabel={t('admin.overview.units')}
              dayLabel={t('admin.overview.day')}
              format={formatUnits}
              formatAxis={краткое}
            />
          </Card>

          <Card title={t('admin.overview.kinds')} desc={t('admin.overview.kindsHint')}>
            {stats.data.jobs_by_kind.length === 0 ? (
              <EmptyState
                compact
                icon="queue"
                title={t('admin.overview.noJobs')}
                text={t('admin.overview.noJobsHint')}
              />
            ) : (
              <KindBars
                rows={stats.data.jobs_by_kind}
                label={t('admin.overview.kinds')}
                labels={{
                  ok: t('admin.overview.legend.ok'),
                  failed: t('admin.overview.legend.failed'),
                  total: t('admin.overview.legend.total'),
                  kind: t('admin.overview.legend.kind'),
                }}
              />
            )}
          </Card>

          <Card
            title={t('admin.overview.registrations')}
            desc={t('admin.overview.registrationsHint')}
          >
            <ColumnChart
              points={регистрации}
              label={t('admin.overview.registrations')}
              valueLabel={t('admin.overview.people')}
              dayLabel={t('admin.overview.day')}
              format={formatUnits}
              formatAxis={краткое}
            />
          </Card>
        </>
      )}
    </div>
  )
}
