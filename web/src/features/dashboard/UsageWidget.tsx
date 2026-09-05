/**
 * UsageWidget — расход и остаток месяца.
 *
 * Всё из одного ответа `GET /api/usage`: план, потолок, потрачено, осталось и
 * первое число расчётного месяца. Складывать это из двух запросов нельзя —
 * они разойдутся, и человек увидит остаток, не равный разнице.
 *
 * Единицы внутренние, и это не скрывается: перевод их в рубли — дело биллинга,
 * которого ещё нет, а выдуманный курс на дашборде был бы враньём.
 */
import { useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { ErrorState, Skeleton } from '@/ui'

import { Widget } from './Widget'

export function UsageWidget() {
  const t = useT()
  const usage = useUsage()

  if (usage.isPending) {
    return (
      <Widget title={t('dashboard.usage.title')}>
        <div className="flex flex-col gap-s3">
          <Skeleton className="h-7 w-1/3" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-3 w-1/4" />
        </div>
      </Widget>
    )
  }

  if (usage.isError || !usage.data) {
    return (
      <Widget title={t('dashboard.usage.title')}>
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      </Widget>
    )
  }

  const { limit_units: потолок, spent_units: потрачено, remaining_units: осталось } = usage.data
  const доля = потолок > 0 ? Math.min(100, Math.round((потрачено / потолок) * 100)) : 0
  const месяц = new Date(usage.data.period_start).toLocaleDateString('ru-RU', {
    month: 'long',
    year: 'numeric',
  })

  return (
    <Widget
      title={t('dashboard.usage.title')}
      note={t('dashboard.usage.plan', { plan: usage.data.plan })}
    >
      <div className="flex h-full flex-col justify-between gap-s3">
        <div className="flex items-baseline gap-s2">
          <span className="font-display text-2xl font-bold tracking-tight text-ink-strong">
            {осталось.toLocaleString('ru-RU')}
          </span>
          <span className="text-sm text-muted">
            {t('dashboard.usage.left', { limit: потолок.toLocaleString('ru-RU') })}
          </span>
        </div>

        <div
          role="meter"
          aria-valuenow={доля}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t('dashboard.usage.title')}
          className="h-2 w-full overflow-hidden rounded-full bg-surface-3"
        >
          <div
            className={доля >= 90 ? 'h-full bg-err' : 'h-full bg-accent'}
            style={{ width: `${доля}%` }}
          />
        </div>

        <p className="text-xs text-muted">
          {t('dashboard.usage.spent', { n: потрачено.toLocaleString('ru-RU'), month: месяц })}
        </p>
      </div>
    </Widget>
  )
}
