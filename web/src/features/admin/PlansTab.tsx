/**
 * PlansTab — справочник планов и сколько людей на каждом.
 *
 * У службы есть справочник (`GET /api/admin/plans`): у плана месячный потолок
 * расхода и квота места, оба числа из настроек.
 * Поэтому таблица наконец показывает планы, а не «те строки, что вписаны
 * людям»: `PATCH /api/admin/users` принимает только имена отсюда и на любое
 * другое отвечает `unknown_plan`.
 *
 * План без людей из таблицы не пропадает: это справочник, а не отчёт, и «на
 * `team` никого» — не то же самое, что «плана `team` нет».
 *
 * План, которого в справочнике нет, а у людей есть, показывается отдельной
 * строкой с пометкой: такие строки остались от времён свободного поля, поставить
 * их сегодня уже нельзя, но молчать про них хуже, чем показать.
 *
 * Расход в строке — сумма по календарному месяцу (то, что отдаёт список людей),
 * а не за период «Обзора»: это разные окна, и складывать их в одну таблицу
 * нельзя.
 */
import { useMemo } from 'react'

import { useT } from '@/i18n'
import { Card, Chip, EmptyState, ErrorState, SkeletonLines } from '@/ui'
import { formatBytes, formatUnits } from '@/features/settings/format'

import { useAdminPlans, useAdminUsers } from './api'
import { CsvButton } from './parts'
import { planRows } from './table'

const TH =
  'whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2'

/** Прочерк вместо числа: у плана вне справочника чисел нет и выдумать их
 *  неоткуда — ноль читался бы как «потолок ноль». */
const НЕТ = '—'

export function PlansTab() {
  const t = useT()
  const users = useAdminUsers()
  const plans = useAdminPlans()
  const строки = useMemo(
    () => planRows(users.data ?? [], plans.data ?? []),
    [users.data, plans.data],
  )

  if (users.isLoading || plans.isLoading) return <SkeletonLines count={6} />
  const беда = users.error ?? plans.error
  if (беда)
    return (
      <ErrorState
        error={беда}
        onRetry={() => {
          void users.refetch()
          void plans.refetch()
        }}
      />
    )

  const всего = строки.reduce((сумма, с) => сумма + с.count, 0)

  return (
    <Card
      title={t('admin.plans.title')}
      desc={t('admin.plans.text')}
      action={
        <CsvButton
          name="koritsu-plans.csv"
          disabled={строки.length === 0}
          headers={[
            t('admin.plans.col.plan'),
            t('admin.plans.col.monthly'),
            t('admin.plans.col.quota'),
            t('admin.plans.col.people'),
            t('admin.plans.col.share'),
            t('admin.plans.col.admins'),
            t('admin.plans.col.spent'),
          ]}
          rows={() =>
            строки.map((с) => [
              с.plan,
              с.monthly_units ?? '',
              с.quota_bytes ?? '',
              с.count,
              всего > 0 ? Math.round((с.count / всего) * 100) : 0,
              с.admins,
              с.spent,
            ])
          }
        />
      }
    >
      {строки.length === 0 ? (
        <EmptyState
          icon="wallet"
          title={t('admin.plans.empty')}
          text={t('admin.plans.emptyHint')}
        />
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className={TH}>{t('admin.plans.col.plan')}</th>
                <th className={`${TH} text-right`}>{t('admin.plans.col.monthly')}</th>
                <th className={`${TH} text-right`}>{t('admin.plans.col.quota')}</th>
                <th className={`${TH} text-right`}>{t('admin.plans.col.people')}</th>
                <th className={TH}>{t('admin.plans.col.share')}</th>
                <th className={`${TH} text-right`}>{t('admin.plans.col.admins')}</th>
                <th className={`${TH} text-right`}>{t('admin.plans.col.spent')}</th>
              </tr>
            </thead>
            <tbody>
              {строки.map((строка) => {
                const доля = всего > 0 ? строка.count / всего : 0
                return (
                  <tr key={строка.plan} className="hover:bg-surface-2">
                    <td className={`${TD} font-medium text-ink-strong`}>
                      <span className="flex flex-wrap items-center gap-1.5">
                        {строка.plan}
                        {строка.unknown && <Chip tone="warn">{t('admin.plans.unknown')}</Chip>}
                      </span>
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right font-mono text-ink`}>
                      {строка.monthly_units === null ? НЕТ : formatUnits(строка.monthly_units)}
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right font-mono text-ink`}>
                      {строка.quota_bytes === null ? НЕТ : formatBytes(строка.quota_bytes)}
                    </td>
                    <td className={`${TD} text-right font-mono text-ink-strong`}>{строка.count}</td>
                    <td className={TD}>
                      {/* Полоска доли — тот же приём, что у места на томе: число
                          читается точнее, а полоска видна быстрее. */}
                      <span className="flex items-center gap-s2">
                        <span
                          aria-hidden="true"
                          className="h-2 w-[120px] overflow-hidden rounded-full bg-surface-2"
                        >
                          <span
                            className="block h-full rounded-full bg-accent"
                            style={{ width: `${Math.round(доля * 100)}%` }}
                          />
                        </span>
                        <span className="font-mono text-xs text-muted">
                          {Math.round(доля * 100)}%
                        </span>
                      </span>
                    </td>
                    <td className={`${TD} text-right font-mono text-muted`}>{строка.admins}</td>
                    <td className={`${TD} text-right font-mono text-ink-strong`}>
                      {formatUnits(строка.spent)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted">{t('admin.plans.hint')}</p>
    </Card>
  )
}
