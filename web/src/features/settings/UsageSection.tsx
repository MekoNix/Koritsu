/**
 * UsageSection — сколько положено за месяц, сколько потрачено, во что обходятся
 * задания.
 *
 * Цены приезжают тем же ответом, что и остаток (`GET /api/usage`), и это не
 * мелочь: остаток месяца и цена задания показываются до нажатия, а два запроса
 * на один экран означали бы два способа увидеть их
 * рассогласованными.
 *
 * Единицы внутренние и в деньги не переводятся: цены поставщиков меняются, а
 * «сколько мне осталось работы» человек читает одним числом.
 */
import { useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { Card, ErrorState, Progress, Row, SkeletonLines } from '@/ui'

import { formatUnits } from './format'

export function UsageSection() {
  const t = useT()
  const usage = useUsage()

  if (usage.isLoading) {
    return (
      <Card title={t('settings.usage.title')}>
        <SkeletonLines count={4} />
      </Card>
    )
  }
  if (usage.error) return <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
  if (!usage.data) return null

  const { plan, limit_units, spent_units, remaining_units, period_start, prices } = usage.data
  const share = limit_units > 0 ? spent_units / limit_units : 0
  const tone = share >= 1 ? 'err' : share >= 0.85 ? 'warn' : 'accent'
  const period = new Date(period_start)

  return (
    <>
      <Card title={t('settings.usage.title')} desc={t('settings.usage.text')}>
        <div className="flex flex-wrap items-end gap-s6">
          <div>
            <div className="font-display text-2xl font-bold leading-none text-ink-strong">
              {formatUnits(spent_units)}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">
              {t('settings.usage.spent')}
            </div>
          </div>
          <div>
            <div className="font-display text-2xl font-bold leading-none text-ink-strong">
              {formatUnits(remaining_units)}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">
              {t('settings.usage.remaining')}
            </div>
          </div>
          <div>
            <div className="font-display text-2xl font-bold leading-none text-ink-strong">
              {Math.round(share * 100)}%
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">
              {t('settings.usage.limit')}
            </div>
          </div>
        </div>

        <Progress value={share} tone={tone} label={t('settings.usage.spent')} />

        <div className="flex flex-col">
          <Row label={t('settings.usage.plan')}>{plan}</Row>
          <Row label={t('settings.usage.limit')}>
            {formatUnits(limit_units)} {t('common.unit.units')}
          </Row>
          <Row label={t('settings.usage.period')}>
            {Number.isNaN(period.getTime())
              ? '—'
              : period.toLocaleDateString('ru-RU', {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric',
                })}
          </Row>
        </div>
      </Card>

      <Card title={t('settings.usage.prices')}>
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted">
                  {t('settings.usage.priceKind')}
                </th>
                <th className="border-b border-line bg-surface px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-muted">
                  {t('settings.usage.priceValue')}
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(prices).map(([kind, price]) => (
                <tr key={kind} className="hover:bg-surface-2">
                  <td className="border-b border-line px-3 py-2 text-ink">
                    {t(`settings.usage.kind.${kind}`) === `settings.usage.kind.${kind}`
                      ? kind
                      : t(`settings.usage.kind.${kind}`)}
                    <span className="ml-s2 font-mono text-xs text-muted">{kind}</span>
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right font-mono text-ink-strong">
                    {formatUnits(price)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
