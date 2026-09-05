/**
 * PlansTab — разбор людей по планам.
 *
 * **Справочника планов у службы нет.** `PATCH /api/admin/users/{id}` принимает
 * `plan` свободной строкой до 32 символов, и маршрута «какие планы бывают» не
 * существует. Поэтому вкладка честно показывает не справочник, а то, что
 * получилось: сколько разных строк вписано людям и сколько людей на каждой.
 * Опечатка видна здесь отдельной строкой — и это скорее польза: иначе её не
 * видно вовсе. Об этом же говорит подпись под таблицей: выдумывать список
 * планов, которого нет, значило бы обещать владельцу справочник, за которым
 * ничего не стоит.
 *
 * Расход в строке — сумма по календарному месяцу (то, что отдаёт список
 * людей), а не за период «Обзора»: это разные окна, и складывать их в одну
 * таблицу нельзя.
 */
import { useMemo } from 'react'

import { useT } from '@/i18n'
import { Card, EmptyState, ErrorState, SkeletonLines } from '@/ui'
import { formatUnits } from '@/features/settings/format'

import { useAdminUsers } from './api'
import { CsvButton } from './parts'
import { planCounts } from './table'

const TH =
  'whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2'

export function PlansTab() {
  const t = useT()
  const users = useAdminUsers()
  const строки = useMemo(() => planCounts(users.data ?? []), [users.data])

  if (users.isLoading) return <SkeletonLines count={6} />
  if (users.error) return <ErrorState error={users.error} onRetry={() => void users.refetch()} />

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
            t('admin.plans.col.people'),
            t('admin.plans.col.share'),
            t('admin.plans.col.admins'),
            t('admin.plans.col.spent'),
          ]}
          rows={() =>
            строки.map((с) => [
              с.plan,
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
        <EmptyState icon="users" title={t('admin.plans.empty')} text={t('admin.plans.emptyHint')} />
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className={TH}>{t('admin.plans.col.plan')}</th>
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
                    <td className={`${TD} font-medium text-ink-strong`}>{строка.plan}</td>
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

      <p className="text-xs text-muted">{t('admin.plans.freeform')}</p>
    </Card>
  )
}
