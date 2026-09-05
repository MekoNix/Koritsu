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
 */
import { useMemo, useState } from 'react'

import { useT } from '@/i18n'
import { Card, Chip, EmptyState, ErrorState, Select, SkeletonLines } from '@/ui'
import { formatMoment } from '@/features/settings/format'

import { EVENTS_LIMIT, useSecurityEvents } from './api'

const TH =
  'sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2 align-top'

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

  return (
    <Card title={t('admin.security.title')} desc={t('admin.security.text')}>
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

      {events.data && events.data.length === 0 && (
        <EmptyState
          icon="shield"
          title={t('admin.security.empty')}
          text={t('admin.security.emptyHint')}
        />
      )}

      {events.data && events.data.length > 0 && (
        <div className="max-h-[60vh] overflow-auto rounded-md border border-line">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className={TH}>{t('admin.security.col.at')}</th>
                <th className={TH}>{t('admin.security.col.kind')}</th>
                <th className={TH}>{t('admin.security.col.user')}</th>
                <th className={TH}>{t('admin.security.col.ip')}</th>
                <th className={TH}>{t('admin.security.col.detail')}</th>
              </tr>
            </thead>
            <tbody>
              {events.data.map((event) => {
                const translated = t(`admin.security.kind.${event.kind}`)
                const detail = Object.entries(event.detail ?? {})
                return (
                  <tr key={event.id} className="hover:bg-surface-2">
                    <td className={`${TD} whitespace-nowrap font-mono text-xs text-muted`}>
                      {formatMoment(event.created_at)}
                    </td>
                    <td className={TD}>
                      <Chip tone={BAD.has(event.kind) ? 'err' : 'muted'}>
                        {translated === `admin.security.kind.${event.kind}`
                          ? event.kind
                          : translated}
                      </Chip>
                    </td>
                    <td className={`${TD} font-mono text-xs text-muted`}>
                      {event.user_id ? `${event.user_id.slice(0, 8)}…` : '—'}
                    </td>
                    <td className={`${TD} font-mono text-xs text-muted`}>{event.ip || '—'}</td>
                    <td className={`${TD} font-mono text-xs text-muted`}>
                      {detail.length === 0
                        ? '—'
                        : detail.map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
                    </td>
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
