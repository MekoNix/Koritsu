/**
 * SecurityTab — журнал событий безопасности, новые сверху.
 *
 * Виды событий служба не перечисляет отдельным маршрутом, поэтому список для
 * фильтра собирается из того, что приехало. Это честнее выдуманного
 * справочника: показывается ровно то, что в журнале есть.
 *
 * Фильтр по виду уходит на службу (`?kind=`), а не отбирается на месте: иначе
 * «показать только отказы входа» показывало бы отказы входа из последней сотни
 * событий, а не последнюю сотню отказов входа.
 *
 * Сортировка, наоборот, считается на месте: служба отдаёт последние `limit`
 * событий новыми сверху и другого порядка не знает. Это не подмена — отсортировать
 * можно только то, что приехало, и порядок «как отдала служба» возвращается
 * третьим щелчком по заголовку.
 */
import { useMemo, useState } from 'react'

import { useT } from '@/i18n'
import { Card, Chip, EmptyState, ErrorState, Select, SkeletonLines } from '@/ui'
import { formatMoment } from '@/features/settings/format'

import { EVENTS_LIMIT, useSecurityEvents } from './api'
import { CsvButton, SortHeader } from './parts'
import { nextSort, sortRows, type SortState } from './table'
import type { SecurityEvent } from './types'

const TD = 'border-b border-line px-3 py-2 align-top'

/** Столбцы, по которым сортируют. */
type Col = 'at' | 'kind' | 'user' | 'ip'

const ПО: Record<Col, (event: SecurityEvent) => string> = {
  at: (e) => e.created_at ?? '',
  kind: (e) => e.kind,
  user: (e) => e.user_id ?? '',
  ip: (e) => e.ip,
}

/** Подробности одной строкой — и для таблицы, и для выгрузки. */
function подробности(event: SecurityEvent): string {
  const поля = Object.entries(event.detail ?? {})
  return поля.length === 0 ? '' : поля.map(([k, v]) => `${k}=${String(v)}`).join(' · ')
}

/** Виды, которые окрашиваются тревожно: это отказы, а не обычная жизнь. */
const BAD = new Set([
  'login_failed',
  'account_locked',
  'rate_limited',
  'csrf_refused',
  'token_revoked',
])

export function SecurityTab() {
  const t = useT()
  const [kind, setKind] = useState('')
  const [sort, setSort] = useState<SortState<Col>>(null)
  const events = useSecurityEvents(kind || null, EVENTS_LIMIT)

  // Виды для фильтра: из того, что приехало сейчас. При выбранном фильтре
  // список сузился бы до одного вида, поэтому он копится в состоянии выбора
  // только когда фильтр снят.
  const [known, setKnown] = useState<string[]>([])
  useMemo(() => {
    if (kind || !events.data) return
    const kinds = Array.from(new Set(events.data.map((e) => e.kind))).sort()
    setKnown((was) => (was.join('|') === kinds.join('|') ? was : kinds))
  }, [kind, events.data])

  const строки = events.data
    ? sort
      ? sortRows(events.data, ПО[sort.col], sort.dir)
      : events.data
    : []
  const сортировать = (col: Col) => setSort((было) => nextSort(было, col))
  const имя = (событие: SecurityEvent) => {
    const переведено = t(`admin.security.kind.${событие.kind}`)
    return переведено === `admin.security.kind.${событие.kind}` ? событие.kind : переведено
  }

  return (
    <Card
      title={t('admin.security.title')}
      desc={t('admin.security.text')}
      action={
        <CsvButton
          name="koritsu-security.csv"
          disabled={строки.length === 0}
          headers={[
            t('admin.security.col.at'),
            t('admin.security.col.kind'),
            t('admin.security.col.user'),
            t('admin.security.col.ip'),
            t('admin.security.col.detail'),
          ]}
          rows={() =>
            строки.map((событие) => [
              событие.created_at ?? '',
              событие.kind,
              событие.user_id ?? '',
              событие.ip,
              подробности(событие),
            ])
          }
        />
      }
    >
      <Select
        label={t('admin.security.filter')}
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        className="max-w-[320px]"
      >
        <option value="">{t('admin.security.filterAll')}</option>
        {known.map((name) => {
          const translated = t(`admin.security.kind.${name}`)
          return (
            <option key={name} value={name}>
              {translated === `admin.security.kind.${name}` ? name : translated}
            </option>
          )
        })}
      </Select>

      {events.isLoading && <SkeletonLines count={8} />}
      {events.error && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}

      {events.data && строки.length === 0 && (
        <EmptyState
          icon="shield"
          title={t('admin.security.empty')}
          text={t('admin.security.emptyHint')}
        />
      )}

      {events.data && строки.length > 0 && (
        <div className="max-h-[60vh] overflow-auto rounded-md border border-line">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <SortHeader col="at" state={sort} onSort={сортировать}>
                  {t('admin.security.col.at')}
                </SortHeader>
                <SortHeader col="kind" state={sort} onSort={сортировать}>
                  {t('admin.security.col.kind')}
                </SortHeader>
                <SortHeader col="user" state={sort} onSort={сортировать}>
                  {t('admin.security.col.user')}
                </SortHeader>
                <SortHeader col="ip" state={sort} onSort={сортировать}>
                  {t('admin.security.col.ip')}
                </SortHeader>
                <th
                  scope="col"
                  className="sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted"
                >
                  {t('admin.security.col.detail')}
                </th>
              </tr>
            </thead>
            <tbody>
              {строки.map((event) => {
                const detail = подробности(event)
                return (
                  <tr key={event.id} className="hover:bg-surface-2">
                    <td className={`${TD} whitespace-nowrap font-mono text-xs text-muted`}>
                      {formatMoment(event.created_at)}
                    </td>
                    <td className={TD}>
                      <Chip tone={BAD.has(event.kind) ? 'err' : 'muted'}>{имя(event)}</Chip>
                    </td>
                    <td className={`${TD} font-mono text-xs text-muted`}>
                      {event.user_id ? `${event.user_id.slice(0, 8)}…` : '—'}
                    </td>
                    <td className={`${TD} font-mono text-xs text-muted`}>{event.ip || '—'}</td>
                    <td className={`${TD} font-mono text-xs text-muted`}>{detail || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
